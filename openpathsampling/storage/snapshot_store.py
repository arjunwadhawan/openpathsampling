from openpathsampling.snapshot import Snapshot, AbstractSnapshot, ToySnapshot
from openpathsampling.trajectory import Trajectory
from openpathsampling.netcdfplus import ObjectStore, LoaderProxy, lazy_loading_attributes

import features as ft
from features import ConfigurationStore, MomentumStore

@lazy_loading_attributes('')
class AbstractSnapshotStore(ObjectStore):
    """
    An ObjectStore for Snapshots in netCDF files.
    """

    def __init__(self, snapshot_class):
        super(AbstractSnapshotStore, self).__init__(AbstractSnapshot, json=False)
        self.snapshot_class = snapshot_class

    def to_dict(self):
        return {
            'snapshot_class': self.snapshot_class
        }

    def _get(self, idx, from_reversed=False):
        if from_reversed:
            obj = self.cache[idx ^ 1]

            return AbstractSnapshot(
                is_reversed=not obj.is_reversed,
                topology=obj.topology,
                reversed_copy=LoaderProxy(self, idx ^ 1)
            )
        else:
            momentum_reversed = self.vars['momentum_reversed'][idx]
            topology = self.storage.topology

            return AbstractSnapshot(
                is_reversed=momentum_reversed,
                topology=topology,
                reversed_copy=LoaderProxy(self, idx ^ 1)
            )

    def _load(self, idx):
        """
        Load a snapshot from the storage.

        Parameters
        ----------
        idx : int
            the integer index of the snapshot to be loaded

        Returns
        -------
        snapshot : Snapshot
            the loaded snapshot instance
        """

        try:
            return self._get(idx, True)
        except KeyError:
            return self._get(idx)

    def _put(self, idx, snapshot):
        self.vars['momentum_reversed'][idx] = snapshot.is_reversed
        self.vars['momentum_reversed'][idx ^ 1] = not snapshot.is_reversed

    def _save(self, snapshot, idx):
        """
        Add the current state of the snapshot in the database.

        Parameters
        ----------
        snapshot : Snapshot()
            the snapshot to be saved
        idx : int or None
            if idx is not None the index will be used for saving in the storage.
            This might overwrite already existing trajectories!

        Notes
        -----
        This also saves all contained frames in the snapshot if not done yet.
        A single Snapshot object can only be saved once!
        """

        self._put(idx, snapshot)

        reversed = snapshot._reversed
        snapshot._reversed = LoaderProxy(self, idx ^ 1)
        reversed._reversed = LoaderProxy(self, idx)

        # mark reversed as stored
        self.index[reversed] = idx ^ 1

    def _init(self):
        """
        Initializes the associated storage to index configuration_indices in it
        """
        super(AbstractSnapshotStore, self)._init()

        self.init_variable('momentum_reversed', 'bool', chunksizes=(1,))

    # =============================================================================================
    # COLLECTIVE VARIABLE UTILITY FUNCTIONS
    # =============================================================================================

    def all(self):
        return Trajectory([LoaderProxy(self, idx) for idx in range(len(self))])

class SnapshotStore(AbstractSnapshotStore):
    """
    An ObjectStore for Snapshots in netCDF files.
    """

    def __init__(self):
        super(SnapshotStore, self).__init__(Snapshot)

    def to_dict(self):
        return {}

    def _put(self, idx, snapshot):
        self.vars['configuration'][idx] = snapshot.configuration
        self.vars['momentum'][idx] = snapshot.momentum
        self.write('configuration', idx ^ 1, snapshot)
        self.write('momentum', idx ^ 1, snapshot)

        self.vars['momentum_reversed'][idx] = snapshot.is_reversed
        self.vars['momentum_reversed'][idx ^ 1] = not snapshot.is_reversed


    def _get(self, idx, from_reversed=False):
        if from_reversed:
            obj = self.cache[idx ^ 1]

            return Snapshot(
                configuration=obj.configuration,
                momentum=obj.momentum,
                is_reversed=not obj.is_reversed,
                topology=obj.topology,
                reversed_copy=LoaderProxy(self, idx ^ 1)
            )
        else:
            configuration = self.vars['configuration'][idx]
            momentum = self.vars['momentum'][idx]
            momentum_reversed = self.vars['momentum_reversed'][idx]
            topology = self.storage.topology

            return Snapshot(
                configuration=configuration,
                momentum=momentum,
                is_reversed=momentum_reversed,
                topology=topology,
                reversed_copy=LoaderProxy(self, idx ^ 1)
            )


    def _init(self):
        """
        Initializes the associated storage to index configuration_indices in it
        """
        super(SnapshotStore, self)._init()

        self.storage.create_store('configurations', ConfigurationStore())
        self.storage.create_store('momenta', MomentumStore())

        self.init_variable('configuration', 'lazyobj.configurations',
                           description="the snapshot index (0..n_configuration-1) of snapshot '{idx}'.",
                           chunksizes=(1,)
                           )

        self.init_variable('momentum', 'lazyobj.momenta',
                           description="the snapshot index (0..n_momentum-1) 'frame' of snapshot '{idx}'.",
                           chunksizes=(1,)
                           )

    # =============================================================================================
    # COLLECTIVE VARIABLE UTILITY FUNCTIONS
    # =============================================================================================

    @property
    def op_configuration_idx(self):
        """
        Returns aa function that returns for an object of this storage the idx

        Returns
        -------
        function
            the function that returns the idx of the configuration
        """

        def idx(obj):
            return self.index[obj.configuration]

        return idx

    @property
    def op_momentum_idx(self):
        """
        Returns aa function that returns for an object of this storage the idx

        Returns
        -------
        function
            the function that returns the idx of the configuration

        """

        def idx(obj):
            return self.index[obj.momentum]

        return idx

class ToySnapshotStore(AbstractSnapshotStore):
    """
    An ObjectStore for Snapshots in netCDF files.
    """

    def __init__(self):
        super(ToySnapshotStore, self).__init__(ToySnapshot)

    def to_dict(self):
        return {}

    def _put(self, idx, snapshot):
        self.vars['coordinates'][idx] = snapshot.coordinates
        self.vars['velocities'][idx] = snapshot.velocities
        self.write('coordinates', idx ^ 1, snapshot)
        self.write('velocities', idx ^ 1, snapshot)

        self.vars['momentum_reversed'][idx] = snapshot.is_reversed
        self.vars['momentum_reversed'][idx ^ 1] = not snapshot.is_reversed

    def _get(self, idx, from_reversed=False):
        if from_reversed:
            obj = self.cache[idx ^ 1]

            return ToySnapshot(
                coordinates=obj.coordinates,
                velocities=obj.velocities,
                is_reversed=not obj.is_reversed,
                topology=obj.topology,
                reversed_copy=LoaderProxy(self, idx ^ 1)
            )
        else:
            coordinates = self.vars['coordinates'][idx]
            velocities = self.vars['velocities'][idx]
            momentum_reversed = self.vars['momentum_reversed'][idx]

            return ToySnapshot(
                coordinates=coordinates,
                velocities=velocities,
                is_reversed=momentum_reversed,
                topology=self.storage.topology,
                reversed_copy=LoaderProxy(self, idx ^ 1)
            )

    def _init(self):
        """
        Initializes the associated storage to index configuration_indices in it
        """
        super(ToySnapshotStore, self)._init()

        n_atoms = self.storage.n_atoms
        n_spatial = self.storage.n_spatial

        self.init_variable('coordinates', 'numpy.float32',
                           dimensions=('atom', 'spatial'),
                           description="coordinate of atom '{ix[1]}' in dimension " +
                                       "'{ix[2]}' of configuration '{ix[0]}'.",
                           chunksizes=(1, n_atoms, n_spatial)
                           )

        self.init_variable('velocities', 'numpy.float32',
                           dimensions=('atom', 'spatial'),
                           description="the velocity of atom 'atom' in dimension " +
                                       "'coordinate' of momentum 'momentum'.",
                           chunksizes=(1, n_atoms, n_spatial)
                           )



    # =============================================================================================
    # COLLECTIVE VARIABLE UTILITY FUNCTIONS
    # =============================================================================================

    @property
    def op_configuration_idx(self):
        """
        Returns aa function that returns for an object of this storage the idx

        Returns
        -------
        function
            the function that returns the idx of the configuration
        """

        def idx(obj):
            return self.index[obj.configuration]

        return idx

    @property
    def op_momentum_idx(self):
        """
        Returns aa function that returns for an object of this storage the idx

        Returns
        -------
        function
            the function that returns the idx of the configuration

        """

        def idx(obj):
            return self.index[obj.momentum]

        return idx

class FeatureSnapshotStore(AbstractSnapshotStore):
    """
    An ObjectStore for Snapshots in netCDF files.
    """

    def __init__(self, snapshot_class):
        super(FeatureSnapshotStore, self).__init__(snapshot_class)

        self._variables = list()

        for feature in self.features:
            self._variables += getattr(ft, feature)._variables

    @property
    def features(self):
        return self.snapshot_class.__features__


    def to_dict(self):
        return {
            'snapshot_class': self.snapshot_class
        }

    def _put(self, idx, snapshot):
        for variable in self._variables:
            self.vars[variable][idx] = getattr(snapshot, variable)
            self.write(variable, idx ^ 1, snapshot)

        self.vars['momentum_reversed'][idx] = snapshot.is_reversed
        self.vars['momentum_reversed'][idx ^ 1] = not snapshot.is_reversed


    def _get(self, idx, from_reversed=False):
        if from_reversed:
            obj = self.cache[idx ^ 1]

            snapshot = self.snapshot_class.__new__(self.snapshot_class)
            AbstractSnapshot.__init__(snapshot, not obj.is_reversed, LoaderProxy(self, idx ^ 1), self.storage.topology)

            for variables in self._variables:
                setattr(snapshot, variables, getattr(obj, variables))

        else:
            snapshot = self.snapshot_class.__new__(self.snapshot_class)
            AbstractSnapshot.__init__(snapshot, self.vars['momentum_reversed'][idx], LoaderProxy(self, idx ^ 1), self.storage.topology)

            for variables in self._variables:
                setattr(snapshot, variables, self.vars[variables][idx])

#        snapshot.topology = self.storage.topology

        return snapshot

    def _init(self):
        super(FeatureSnapshotStore, self)._init()

        for feature in self.features:
            getattr(ft, feature)._init(self)
