import openpathsampling as paths
from openpathsampling.tools import refresh_output

from move_strategy import levels as strategy_levels
# import move_strategy as move_strategy
import move_strategy
from openpathsampling.netcdfplus import StorableNamedObject

try:
    import pandas as pd
    has_pandas = True
except ImportError:
    has_pandas = False
    pd = None


import sys


class MoveScheme(StorableNamedObject):
    """
    Creates a move decision tree based on `MoveStrategy` instances.

    Attributes
    ----------
    movers : dict
        Dictionary mapping mover group as key to list of movers
    strategies : dict
        Dictionary mapping level (number) to list of strategies
    root_mover : PathMover
        Root of the move decision tree (`None` until tree is built)
    """
    def __init__(self, network):
        super(MoveScheme, self).__init__()
        self.movers = {}
        self.network = network
        self.strategies = {}
        self.balance_partners = {}
        self.choice_probability = {}
        self._real_choice_probability = {}  # used as override, e.g., in SRTIS
        self.root_mover = None

        self._mover_acceptance = {}  # used in analysis

    def to_dict(self):
        ret_dict = {
            'movers': self.movers,
            'network': self.network,
            'choice_probability': self.choice_probability,
            'real_choice_probability': self.real_choice_probability,
            'balance_partners': self.balance_partners,
            'root_mover': self.root_mover,
        }
        return ret_dict

    @classmethod
    def from_dict(cls, dct):
        scheme = cls.__new__(cls)
        # noinspection PyArgumentList
        scheme.__init__(dct['network'])
        scheme.movers = dct['movers']
        scheme.choice_probability = dct['choice_probability']
        scheme._real_choice_probability = dct['real_choice_probability']
        scheme.balance_partners = dct['balance_partners']
        scheme.root_mover = dct['root_mover']
        return scheme

    @property
    def real_choice_probability(self):
        if self._real_choice_probability == {}:
            return self.choice_probability
        else:
            return self._real_choice_probability

    @real_choice_probability.setter
    def real_choice_probability(self, value):
        self._real_choice_probability = value

    def append(self, strategies, levels=None, force=False):
        """
        Adds new strategies to this scheme, organized by `level`.

        Parameters
        ----------
        strategies : MoveStrategy or list of MoveStrategy
            strategies to add to this scheme
        levels : integer or list of integer or None
            levels to associate with each strategy. If None, strategy.level.
        force : bool
            force the strategy to be appended, even if a root_mover exists.
            Default False for safety.
        """
        # first we clean up the input: strategies is a list of MoveStrategy;
        # levels is a list of integers
        if self.root_mover is not None:
            if force:
                self.root_mover = None
            else:
                raise RuntimeError("Can't add strategies after the move " +
                                   "decision tree has been built. " +
                                   "Override with `force=True`.")

        try:
            strategies = list(strategies)
        except TypeError:
            strategies = [strategies]

        if levels is not None:
            try:
                levels = list(levels)
            except TypeError:
                levels = [levels]*len(strategies)
        else:
            levels = []
            for strat in strategies:
                levels.append(strat.level)
        
        # now we put everything into appropriate dictionaries
        for strat, lev in zip(strategies, levels):
            try:
                self.strategies[lev].append(strat)
            except KeyError:
                self.strategies[lev] = [strat]

    # TODO: it might be nice to have a way to "lock" this once it has been
    # saved. That would prevent a (stupid) user from trying to rebuild a
    # custom-modified tree.
    def build_move_decision_tree(self):
        for lev in sorted(self.strategies.keys()):
            for strat in self.strategies[lev]:
                self.apply_strategy(strat)

    # TODO: should I make this a property? make root_mover into
    # _move_decision_tree? allow the user to directly set it? rename as
    # move_scheme? separated from building until some of that is clarified
    def move_decision_tree(self, rebuild=False):
        """
        Returns the move decision tree.

        Parameters
        ----------
        rebuild : bool, optional
            Whether to rebuild the tree, or use the previously build version
            (default is False, if no tree exists, sets to True)

        Returns
        -------
        PathMover
            Root mover of the move decision tree
        """
        if self.root_mover is None:
            rebuild = True
        if rebuild:
            self.choice_probability = {}
            self.build_move_decision_tree()
        return self.root_mover

    def apply_strategy(self, strategy):
        """
        Applies given strategy to the scheme as it stands.

        This is the tool used in the process of building up the move
        decision tree. 

        Parameters
        ----------
        strategy : MoveStrategy
            the strategy to apply
        """
        movers = strategy.make_movers(self)
        group = strategy.group
        if strategy_levels.level_type(strategy.level) == strategy_levels.GLOBAL:
            # shortcut out for the global-level stuff
            self.root_mover = movers
        elif strategy.replace_signatures:
            self.movers[group] = movers
        elif strategy.replace_movers:
            try:
                n_existing = len(self.movers[group])
            except KeyError:
                # if the group doesn't exist, set it to these movers
                self.movers[group] = movers
            else:
                # Note that the following means that if the list of new
                # movers includes two movers with the same sig, the second
                # will overwrite the first. This is desired behavior. On the
                # other hand, if the list of old movers in the group already
                # has two movers with the same signature, then both should
                # be overwritten.
                existing_sigs = {}
                for i in range(n_existing):
                    key = self.movers[group][i].ensemble_signature
                    try:
                        existing_sigs[key].append(i)
                    except KeyError:
                        existing_sigs[key] = [i]

                # For each mover, if its signature exists in the existing
                # movers, replace the existing. Otherwise, append it to the
                # list.
                for mover in movers:
                    m_sig = mover.ensemble_signature
                    if m_sig in existing_sigs.keys():
                        for idx in existing_sigs[m_sig]:
                            self.movers[group][idx] = mover
                    else:
                        self.movers[group].append(mover)
        elif strategy.replace_group:
            if strategy.from_group is not None:
                self.movers.pop(strategy.from_group)
            self.movers[group] = movers
        else:
            try:
                self.movers[group].extend(movers)
            except KeyError:
                self.movers[group] = movers

    def ensembles_for_move_tree(self, root=None):
        """
        Finds the list of all ensembles in the move tree starting at `root`.

        Parameters
        ----------
        root : PathMover
            Mover to act as root of this tree (can be a subtree). Default is
            `None`, in which case `self.root_mover` is used.

        Returns
        -------
        list of Ensemble
            ensembles which appear in this (sub)tree
        """
        if root is None:
            if self.root_mover is None:
                self.root_mover = self.move_decision_tree()

            root = self.root_mover
        movers = root.map_pre_order(lambda x: x)
        mover_ensemble_dict = {}
        for m in movers:
            input_sig = m.input_ensembles
            output_sig = m.output_ensembles
            for ens in input_sig + output_sig:
                mover_ensemble_dict[ens] = 1
        mover_ensembles = mover_ensemble_dict.keys()
        return mover_ensembles

    def find_hidden_ensembles(self, root=None):
        """
        All ensembles which exist in the move scheme but not in the network.

        Hidden ensembles are typically helper ensembles for moves; for
        example, the minus move uses a "segment" helper ensemble which is
        almost, but not quite, the innermost interface ensemble.

        Parameters
        ----------
        root : PathMover
            Mover to act as root of this tree (can be a subtree). Default is
            `None`, in which case `self.root_mover` is used.

        Returns
        -------
        set of Ensemble
            "hidden" ensembles; the ensembles which are in the scheme but
            not the network.
        """
        unhidden_ensembles = set(self.network.all_ensembles)
        mover_ensembles = set(self.ensembles_for_move_tree(root))
        hidden_ensembles = mover_ensembles - unhidden_ensembles
        return hidden_ensembles

    def find_unused_ensembles(self, root=None):
        """
        All ensembles which exist in the network but not in the move scheme.

        Not all move schemes will use all the ensembles. For example, a move
        scheme might choose not to use the network's automatically generated
        minus ensemble or multistate ensemble.

        Parameters
        ----------
        root : PathMover
            Mover to act as root of this tree (can be a subtree). Default is
            `None`, in which case `self.root_mover` is used.

        Returns
        -------
        set of Ensemble
            "unused" ensembles; the ensembles which are in the network but
            not the scheme.
        """
        unhidden_ensembles = set(self.network.all_ensembles)
        mover_ensembles = set(self.ensembles_for_move_tree(root))
        unused_ensembles = unhidden_ensembles - mover_ensembles
        return unused_ensembles

    def find_used_ensembles(self, root=None):
        """
        All ensembles which are both in the network and in the move scheme.

        """
        unhidden_ensembles = set(self.network.all_ensembles)
        mover_ensembles = set(self.ensembles_for_move_tree(root))
        used_ensembles = unhidden_ensembles & mover_ensembles
        return used_ensembles

    def check_for_root(self, fcn_name):
        """
        Raises runtime warning if self.root_mover not set.

        Some functions are only valid after the decision tree has been
        built. This complains if the tree is not there.
        """
        if self.root_mover is None:
            warnstr = ("Can't use {fcn_name} before building the move " +
                       "decision tree").format(fcn_name=fcn_name)
            raise RuntimeWarning(warnstr)

    def list_initial_ensembles(self, root=None):
        """
        Returns a list of initial ensembles for this move scheme.
        
        Used in `initial_conditions_from_trajectories` to get the ensembles
        we need. The list returned by this is of a particular format: it
        should be thought of as a list of lists of ensembles. Call this the
        "list" and the "sublists". At least one member of each sublist is
        required, and if a "sublist" is actually an ensemble, it is treated
        as a sublist of one. So returning [a, b, [c, d], e] is equivalent to
        returning [[a], [b], [c, d], [e]], and is interpreted as "initial
        conditions are ensembles a, b, e, and one of either c or d".

        To make the simplest cases more explicit, normal all-replica TIS for
        ensembles a, b, and c would return [a, b, c], or equivalently, [[a],
        [b], [c]]. Single-replica TIS would return [[a, b, c]].
        """
        # basically, take the find_used_ensembles and return them in the
        # canonical order from network.all_ensembles
        used_ensembles = self.find_used_ensembles(root)
        output_ensembles = [ens for ens in self.network.all_ensembles
                            if ens in used_ensembles]
        return output_ensembles

    def initial_conditions_from_trajectories(self, trajectories,
                                             sample_set=None,
                                             strategies=None,
                                             preconditions=None,
                                             reuse_strategy='avoid-symmetric',
                                             engine=None):
        """
        Create a SampleSet with as many initial samples as possible.

        The goal of this is to give the initial SampleSet that would be
        desired. 

        Parameters
        ----------
        trajectories : list of :class:`.Trajectory` or :class:`.Trajectory`
            the input trajectories to use
        sample_set : :class:`.SampleSet`, optional
            if given, add samples to this sampleset. Default is None, which
            means that this will start a new sampleset.
        strategies : dict
            a dict that specifies the options used when ensemble functions
            are used to create a new sample.
        preconditions : list of str
            a list of possible steps to modify the initial list of trajectories.
            possible choices are

                1.  `sort-shortest` - sorting by shortest first,
                2.  `sort_median` - sorting by the middle one first and then in
                    move away from the median length
                3.  `sort-longest` - sorting by the longest first
                4.  `reverse` - reverse the order and
                5.  `mirror` which will add the reversed trajectories to the
                    list in the same order

            Default is `None` which means to do nothing.
        reuse_strategy : str
            if `avoid` then reusing the same same trajectory twice is avoided.
            `avoid-symmetric` will also remove reversed copies
            if possible. `all` will not attempt to avoid already existing ones.
            `once` will strictly not reuse a trajectory and `once-symmetric`
            will also not use reversed copies.
        engine : :class:`openpathsampling.engines.DyanmicsEngine`
            the engine used for extending moves

        Returns
        -------
        :class:`.SampleSet`
            sampleset with samples for every initial ensemble for this
            scheme that could be satisfied by the given trajectories

        See Also
        --------
        list_initial_ensembles
        check_initial_conditions
        assert_initial_conditions
        """

        if sample_set is None:
            sample_set = paths.SampleSet([])

        ensembles = self.list_initial_ensembles()

        sample_set = sample_set.generate_from_trajectories(
            ensembles,
            trajectories,
            preconditions,
            strategies,
            reuse_strategy,
            engine
        )
        refresh_output(self.initial_conditions_report(sample_set),
                       ipynb_display_only=True, print_anyway=False)
        return sample_set



    def check_initial_conditions(self, sample_set):
        """
        Check for missing or extra ensembles for initial conditions.

        This is primary used programmatically as a reusable function for
        several use cases where we need this information. See functions
        under "see also" for examples of such cases.

        Parameters
        ----------
        sample_set : :class:`.SampleSet`
            proposed set of initial conditions for this movescheme

        Returns
        -------
        missing : list of list of :class:`.Ensemble`
            ensembles needed by the move scheme and missing in the sample
            set, in the format used by `list_initial_ensembles`
        extra : list of :class:`.Ensemble`
            ensembles in the sampleset that are not used by the

        See Also
        --------
        list_initial_ensembles
        assert_initial_conditions
        initial_conditions_report
        """

        return sample_set.check_ensembles(self.list_initial_ensembles())

    def assert_initial_conditions(self, sample_set, allow_extras=False):
        """
        Assertion that the given sampleset is good for initial conditions.

        Parameters
        ----------
        sample_set : :class:`.SampleSet`
            proposed set of initial conditions for this movescheme
        allow_extras : bool
            whether extra ensembles are allowed, default False, meaning the
            extra ensembles raise an assertion error

        Raises
        ------
        AssertionError
            the proposed initial conditions are not valid for this scheme

        See Also
        --------
        check_initial_conditions
        initial_conditions_report
        """
        (missing, extras) = self.check_initial_conditions(sample_set)
        msg = ""
        if len(missing) > 0:
            msg += "Missing ensembles: " + str(missing) + "\n"
        if len(extras) > 0 and not allow_extras:
            msg += "Extra ensembles: " + str(extras) + "\n"
        if msg != "":
            raise AssertionError("Bad initial conditions.\n" + msg)

    def initial_conditions_report(self, sample_set):
        """
        String report on whether the given SampleSet gives good initial
        conditions.

        This is intended to provide a user-friendly tool for interactive
        setup.

        Parameters
        ----------
        sample_set : :class:`.SampleSet`
            proposed set of initial conditions for this movescheme

        Returns
        -------
        str
            a human-readable string describing if (and which) ensembles are
            missing
        """
        (missing, extra) = self.check_initial_conditions(sample_set)
        msg = ""
        if len(missing) == 0:
            msg += "No missing ensembles.\n"
        else:
            msg += "Missing ensembles:\n"
            for ens_list in missing:
                msg += "*  [" 
                msg += ", ".join([ens.name for ens in ens_list]) + "]\n"
        if len(extra) == 0:
            msg += "No extra ensembles.\n"
        else:
            msg += "Extra ensembles:\n"
            for ens in extra:
                msg += "*  " + ens.name + "\n"
        return msg

    def build_balance_partners(self):
        """
        Create list of balance partners for all movers in groups.

        The balance partners are the movers in the same mover group which
        have the opposite ensemble signature (input and output switched).
        These are used when dynamically calculating detailed balance.

        Note
        ----
        Currently, every mover in a group must have exactly one balance
        partner.  In the future, this might be relaxed to "at least one".
        """
        self.check_for_root("build_balance_partners")
        for groupname in self.movers.keys():
            group = self.movers[groupname]
            for mover in group:
                partner_sig_set = (set(mover.output_ensembles), 
                                   set(mover.input_ensembles))
                partners = [m for m in group 
                            if m.ensemble_signature_set == partner_sig_set]
                self.balance_partners[mover] = partners
                if len(partners) != 1:
                    warnstr = "Mover {0}: number of balance partners is {1}"
                    raise RuntimeWarning(warnstr.format(mover, len(partners)))
        return self.balance_partners

    def _select_movers(self, input_mover):
        """
        Return list of movers from group name, list of movers, or mover.

        Mainly used to regularize input for other functions.

        Parameters
        ----------
        input_mover : PathMover or list of PathMover or string
        
        Returns
        -------
        list of PathMover
            If `input_mover` is list of PathMovers, returns same. If
            `input_mover` is PathMover, wraps it in a list. If `input_mover`
            is a string, uses that key in self.movers.
        """
        try:
            movers = self.movers[input_mover]
        except TypeError:  # unhashable type: 'list'
            movers = input_mover
        except KeyError:  # input_mover not found
            movers = [input_mover]

        # here we do a little type-checking
        for m in movers:
            try:
                assert(isinstance(m, paths.PathMover))
            except AssertionError:
                msg = ("Bad output from _select_movers: " + str(movers) 
                       + "; " + repr(m) + " is not a PathMover\n")
                msg += ("Are you using a group name before building the "
                        + "move decision tree?")
                raise TypeError(msg)
        return movers

    def n_steps_for_trials(self, mover, n_attempts):
        """
        Return number of MC steps to expect `n_attempts` trials of `mover`.

        Read this as "To get `n_attempts` trials of `mover`, you need around
        `scheme.n_steps_for_trials(mover, n_attempts)` MC steps. If `mover`
        is a (string) key for a group, then return the total for that group.
        If mover is a list of movers, return the total for that list.
        
        Parameters
        ----------
        mover : PathMover or list of PathMover or string
            The mover of interest. See MoveScheme._select_movers for
            interpretation.
        n_attempts : The desired number of attempts of `mover`

        Returns
        -------
        float
            expected number of steps to get `n_attempts` of `mover`
        """
        movers = self._select_movers(mover)
        total_probability = sum([self.real_choice_probability[m] 
                                 for m in movers])
        return n_attempts / total_probability

    def n_trials_for_steps(self, mover, n_steps):
        """
        Return number of attempts expected for `mover` after `n_steps`.

        Read this as "If you run `n_steps` Monte Carlo steps, you can expect
        to have about `scheme.n_trials_in_steps(mover, n_steps)` trials of
        `mover`.  If `mover` is a (string) key for a group, then return the
        total for that group.  If mover is a list of movers, return the
        total for that list.
        
        Parameters
        ----------
        mover : PathMover or list of PathMover or string
            The mover of interest. See MoveScheme._select_movers for
            interpretation.
        n_steps : The number of hypothetical MC steps

        Returns
        -------
        float
            expected number of trials of `mover` in `n_steps` MC steps
        """
        movers = self._select_movers(mover)
        total_probability = sum([self.real_choice_probability[m] 
                                 for m in movers])
        return total_probability * n_steps

    def sanity_check(self):
        # check that all sampling ensembles are used
        sampling_transitions = self.network.sampling_transitions
        all_sampling_ensembles = sum(
            [t.ensembles for t in sampling_transitions], []
        )
        unused = self.find_unused_ensembles()
        for ens in unused:
            try:
                assert(ens not in all_sampling_ensembles)
            except AssertionError as e:
                failmsg = "Sampling ensemble {ens} unused in move scheme {s}\n"
                e.args = [failmsg.format(ens=ens.name, s=self)]
                raise

        # check that choice_probability adds up
        total_choice = sum(self.choice_probability.values())
        try:
            assert(abs(total_choice - 1.0) < 1e-7)
        except AssertionError as e:
            failmsg = "Choice probability not normalized for scheme {s}\n"
            e.args = [failmsg.format(s=self)]
            raise

        # check for duplicated movers in groups
        all_movers = sum(self.movers.values(), [])
        all_unique_movers = set(all_movers)
        try:
            assert(len(all_movers) == len(all_unique_movers))
        except AssertionError as e:
            failmsg = "At least one group-level mover duplicated " \
                      "in scheme {s}\n"
            e.args = [failmsg.format(s=self)]
            raise

        # note that the test for the same ens sig is part of the balance
        # calc
        return True  # if we get here, then we must have passed tests

    def _move_summary_line(self, move_name, n_accepted, n_trials,
                           n_total_trials, expected_frequency, indentation):
        try:
            acceptance = float(n_accepted) / n_trials
        except ZeroDivisionError:
            acceptance = float("nan")

        line = ("* "*indentation + str(move_name) +
                " ran " + "{:.3%}".format(float(n_trials)/n_total_trials) +
                " (expected {:.2%})".format(expected_frequency) + 
                " of the cycles with acceptance " + str(n_accepted) + "/" +
                str(n_trials) + " ({:.2%})\n".format(acceptance))
        return line

    def move_acceptance(self, steps):
        for step in steps:
            delta = step.change
            for m in delta:
                acc = 1 if m.accepted else 0
                key = (m.mover, str(delta.key(m)))
                is_trial = 1
                # if hasattr(key[0], 'counts_as_trial'):
                    # is_trial = 1 if key[0].counts_as_trial else 0

                try:
                    self._mover_acceptance[key][0] += acc
                    self._mover_acceptance[key][1] += is_trial
                except KeyError:
                    self._mover_acceptance[key] = [acc, is_trial]

    def move_summary(self, steps, movers=None, output=sys.stdout, depth=0):
        """
        Provides a summary of the movers in `steps`.

        The summary includes the number of moves attempted and the
        acceptance rate. In some cases, extra lines are printed for each of
        the submoves.

        Parameters
        ----------
        steps : iterable of :class:`.MDStep`
            steps to analyze
        movers : None or string or list of PathMover
            If None, provides a short summary of the keys in self.mover. If
            a string, provides a short summary using that string as a key in
            the `movers` dict. If a mover or list of movers, provides
            summary for each of those movers.
        output : file
            file to direct output
        depth : integer or None
            depth of submovers to show: if integer, shows that many
            submovers for each move; if None, shows all submovers
        """
        my_movers = {}
        expected_frequency = {}
        if movers is None:
            movers = self.movers.keys()
        if type(movers) is str:
            movers = self.movers[movers]
        for key in movers:
            try:
                my_movers[key] = self.movers[key]
            except KeyError:
                my_movers[key] = [key]


        stats = {}
        for groupname in my_movers.keys():
            stats[groupname] = [0, 0]

        if self._mover_acceptance == {}:
            self.move_acceptance(steps)

        no_move_keys = [k for k in self._mover_acceptance.keys()
                        if k[0] is None]
        n_in_scheme_no_move_trials = sum([self._mover_acceptance[k][1]
                                          for k in no_move_keys
                                          if k[1] != '[None]'])
        n_no_move_trials = sum([self._mover_acceptance[k][1]
                                for k in self._mover_acceptance.keys()
                                if k[0] is None])
        tot_trials = len(steps) - n_no_move_trials
        if n_in_scheme_no_move_trials > 0:
            output.write(
                "Null moves for " + str(n_in_scheme_no_move_trials)
                + " cycles. Excluding null moves:\n"
            )
        for groupname in my_movers.keys():
            group = my_movers[groupname]
            for mover in group:
                key_iter = (k for k in self._mover_acceptance.keys()
                            if k[0] is mover)

                for k in key_iter:
                    stats[groupname][0] += self._mover_acceptance[k][0]
                    stats[groupname][1] += self._mover_acceptance[k][1]
            try:
                # if null moves don't count
                expected_frequency[groupname] = sum(
                    [self.choice_probability[m] for m in group]
                )
                ## if null moves count
                # expected_frequency[groupname] = sum(
                    # [self.real_choice_probability[m] for m in group]
                # )
            except KeyError:
                expected_frequency[groupname] = float('nan')

        for groupname in my_movers.keys():
            if has_pandas and isinstance(output, pd.DataFrame):
                # TODO Pandas DataFrame Output
                pass
            else:
                line = self._move_summary_line(
                    move_name=groupname, 
                    n_accepted=stats[groupname][0],
                    n_trials=stats[groupname][1], 
                    n_total_trials=tot_trials,
                    expected_frequency=expected_frequency[groupname],
                    indentation=0
                )
                output.write(line)
                # raises AttributeError if no write function


class DefaultScheme(MoveScheme):
    """
    Just a MoveScheme with the full set of default strategies: nearest
    neighbor repex, uniform selection one-way shooting, minus move, and
    path reversals, all structured as choose move type then choose specific
    move.
    """
    def __init__(self, network, engine=None):
        super(DefaultScheme, self).__init__(network)
        n_ensembles = len(network.sampling_ensembles)
        self.append(move_strategy.NearestNeighborRepExStrategy())
        self.append(move_strategy.OneWayShootingStrategy(engine=engine))
        self.append(move_strategy.PathReversalStrategy())
        self.append(move_strategy.MinusMoveStrategy(engine=engine))
        global_strategy = move_strategy.OrganizeByMoveGroupStrategy()
        self.append(global_strategy)

        try:
            msouters = self.network.special_ensembles['ms_outer']
        except KeyError:
            # if no ms_outer, ignore the ms_outer setup for now; later we
            # might default to a state swap
            pass
        else:
            for ms in msouters.keys():
                self.append(move_strategy.OneWayShootingStrategy(
                    ensembles=[ms],
                    group="ms_outer_shooting",
                    engine=engine
                ))
                self.append(move_strategy.PathReversalStrategy(
                    ensembles=[ms],
                    replace=False
                ))
                ms_neighbors = [t.ensembles[-1] for t in msouters[ms]]
                pairs = [[ms, neighb] for neighb in ms_neighbors]
                self.append(move_strategy.SelectedPairsRepExStrategy(
                    ensembles=pairs
                ))


class LockedMoveScheme(MoveScheme):
    def __init__(self, root_mover, network=None, root_accepted=None):
        super(LockedMoveScheme, self).__init__(network)
        self.root_mover = root_mover

    def append(self, strategies, levels=None, force=False):
        raise TypeError("Locked schemes cannot append strategies")

    def build_move_decision_tree(self):
        # override with no-op
        pass

    def move_decision_tree(self, rebuild=False):
        return self.root_mover
    
    def apply_strategy(self, strategy):
        raise TypeError("Locked schemes cannot apply strategies")

    def to_dict(self):
        # things that we always have (from MoveScheme)
        ret_dict = {
            'network': self.network,
            'balance_partners': self.balance_partners,
            'root_mover': self.root_mover,
            'movers': self._movers,
            'choice_probability': self._choice_probability,
            'real_choice_probability': self._real_choice_probability}

        # things that LockedMoveScheme overrides
        return ret_dict

    @property
    def choice_probability(self):
        if self._choice_probability == {}:
            raise AttributeError("'choice_probability' must be manually " + 
                                 "set in 'LockedMoveScheme'")
        else:
            return self._choice_probability

    @choice_probability.setter
    def choice_probability(self, vals):
        self._choice_probability = vals

    @property
    def movers(self):
        if self._movers == {}:
            raise AttributeError("'movers' must be manually " + 
                                 "set in 'LockedMoveScheme'")
        else:
            return self._movers

    @movers.setter
    def movers(self, vals):
        self._movers = vals


class SRTISScheme(DefaultScheme):
    """
    This gives exactly the DefaultMoveScheme, but as an SRTIS setup.
    """
    def __init__(self, network, bias=None, engine=None):
        super(SRTISScheme, self).__init__(network, engine)
        sr_minus_strat = move_strategy.SingleReplicaMinusMoveStrategy(
            engine=engine
        )
        sr_minus_strat.level = move_strategy.levels.SUPERGROUP  # GROUP?
        # maybe this should be the default for that strategy anyway? using it
        # at mover-level seems less likely than group-level
        self.append([move_strategy.PoorSingleReplicaStrategy(),
                     move_strategy.EnsembleHopStrategy(bias=bias),
                     sr_minus_strat])


class OneWayShootingMoveScheme(MoveScheme):
    """
    MoveScheme with only a OneWayShooting strategy.

    Useful for building on top of. Useful as default for TPS.
    """
    def __init__(self, network, selector=None, ensembles=None, engine=None):
        super(OneWayShootingMoveScheme, self).__init__(network)
        self.append(move_strategy.OneWayShootingStrategy(selector=selector,
                                                         ensembles=ensembles,
                                                         engine=engine))
        self.append(move_strategy.OrganizeByMoveGroupStrategy())
