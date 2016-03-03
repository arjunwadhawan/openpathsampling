import copy

import numpy as np
from simtk import unit as u

from openpathsampling.netcdfplus import StorableObject, ObjectStore

# =============================================================================
# SIMULATION CONFIGURATION
# =============================================================================

class Configuration(StorableObject):
    """
    Simulation configuration. Only Coordinates, the associated boxvectors
    and the potential_energy

    Attributes
    ----------
    coordinates : simtk.unit.Quantity wrapping Nx3 np array of dimension length
        atomic coordinates
    box_vectors : periodic box vectors
        the periodic box vectors

    """

    # Class variables to store the global storage and the system context
    # describing the system to be safed as configuration_indices

    def __init__(self, coordinates, box_vectors):
        """
        Create a simulation configuration from either an OpenMM context or
        individually-specified components.

        Parameters
        ----------
        coordinates
        box_vectors
        """

        super(Configuration, self).__init__()

        self.coordinates = copy.deepcopy(coordinates)
        self.box_vectors = copy.deepcopy(box_vectors)

        if self.coordinates is not None:
            # Check for nans in coordinates, and raise an exception if
            # something is wrong.
            if type(self.coordinates) is u.Quantity:
                coords = self.coordinates._value
            else:
                coords = self.coordinates

            if np.any(np.isnan(coords)):
                raise ValueError(
                    "Some coordinates became 'nan'; simulation is unstable or buggy.")

        return

    # =========================================================================
    # Comparison functions
    # =========================================================================

    @property
    def n_atoms(self):
        """
        Returns the number of atoms in the configuration
        """
        return self.coordinates.shape[0]

    # =========================================================================
    # Utility functions
    # =========================================================================

    def copy(self):
        """
        Returns a deep copy of the instance itself using a subset of coordinates.
        If this object is saved it will be stored as a separate object and
        consume additional memory.

        Returns
        -------
        Configuration()
            the reduced deep copy
        """

        # TODO: Keep old potential_energy? Is not correct but might be useful. Boxvectors are fine!
        return Configuration(coordinates=self.coordinates,
                             box_vectors=self.box_vectors
                             )


class ConfigurationStore(ObjectStore):
    """
    An ObjectStore for Configuration. Allows to store Configuration() instances in a netcdf file.
    """
    def __init__(self):
        super(ConfigurationStore, self).__init__(Configuration, json=False)

    def to_dict(self):
        return {}

    def _save(self, configuration, idx):
        # Store configuration.
        self.vars['coordinates'][idx] = configuration.coordinates

        if configuration.box_vectors is not None:
            self.vars['box_vectors'][idx] = configuration.box_vectors

    def get(self, indices):
        return [self.load(idx) for idx in indices]

    def _load(self, idx):
        coordinates = self.vars["coordinates"][idx]
        box_vectors = self.vars["box_vectors"][idx]

        configuration = Configuration(coordinates=coordinates, box_vectors=box_vectors)
        configuration.topology = self.storage.topology

        return configuration

    def coordinates_as_numpy(self, frame_indices=None, atom_indices=None):
        """
        Return the atom coordinates in the storage for given frame indices
        and atoms

        Parameters
        ----------
        frame_indices : list of int or None
            the frame indices to be included. If None all frames are returned
        atom_indices : list of int or None
            the atom indices to be included. If None all atoms are returned

        Returns
        -------
        numpy.array, shape=(n_frames, n_atoms)
            the array of atom coordinates in a float32 numpy array

        """
        if frame_indices is None:
            frame_indices = slice(None)

        if atom_indices is None:
            atom_indices = slice(None)

        return self.storage.variables[self.prefix + '_coordinates'][frame_indices, atom_indices, :].astype(
            np.float32).copy()

    def _init(self):
        super(ConfigurationStore, self)._init()
        n_atoms = self.storage.n_atoms
        n_spatial = self.storage.n_spatial

        snapshot = self.storage.template

        unit = None

        if snapshot.coordinates is not None:
            if hasattr(snapshot.coordinates, 'unit'):
                unit = snapshot.coordinates.unit

        self.create_variable('coordinates', 'numpy.float32',
                           dimensions=('atom', 'spatial'),
                           description="coordinate of atom '{ix[1]}' in dimension " +
                                       "'{ix[2]}' of configuration '{ix[0]}'.",
                           chunksizes=(1, n_atoms, n_spatial),
                           simtk_unit=unit
                           )

        self.create_variable('box_vectors', 'numpy.float32',
                           dimensions=('spatial', 'spatial'),
                           chunksizes=(1, n_spatial, n_spatial),
                           simtk_unit=unit
                           )

# =============================================================================
# SIMULATION MOMENTUM / VELOCITY
# =============================================================================

class Momentum(StorableObject):
    """
    Simulation momentum. Contains only velocities of all atoms and
    associated kinetic energies

    Attributes
    ----------
    velocities : simtk.unit.Quantity wrapping Nx3 np array of dimension length
        atomic velocities

    """

    def __init__(self, velocities):
        """
        Create a simulation momentum from either an OpenMM context or
        individually-specified components.

        Parameters
        ----------
        velocities
        """

        super(Momentum, self).__init__()

        self.velocities = copy.deepcopy(velocities)

    # =========================================================================
    # Utility functions
    # =========================================================================

    def copy(self):
        """
        Returns a deep copy of the instance itself. If saved this object will
        be stored as a separate object and consume additional memory.

        Returns
        -------
        Momentum()
            the shallow copy
        """

        this = Momentum(velocities=self.velocities)

        return this


class MomentumStore(ObjectStore):
    """
    An ObjectStore for Momenta. Allows to store Momentum() instances in a netcdf file.
    """

    def __init__(self):
        super(MomentumStore, self).__init__(Momentum, json=False)

    def to_dict(self):
        return {}

    def _save(self, momentum, idx):
        self.vars['velocities'][idx, :, :] = momentum.velocities

    def _load(self, idx):
        velocities = self.vars['velocities'][idx]

        momentum = Momentum(velocities=velocities)
        return momentum

    def velocities_as_numpy(self, frame_indices=None, atom_indices=None):
        """
        Return a block of stored velocities in the database as a numpy array.

        Parameters
        ----------
        frame_indices : list of int or None
            the indices of Momentum objects to be retrieved from the database.
            If `None` is specified then all indices are returned!
        atom_indices : list of int of None
            if not None only the specified atom_indices are returned. Might
            speed up reading a lot.
        """

        if frame_indices is None:
            frame_indices = slice(None)

        if atom_indices is None:
            atom_indices = slice(None)

        return self.variables['velocities'][frame_indices, atom_indices, :].astype(np.float32).copy()

    def velocities_as_array(self, frame_indices=None, atom_indices=None):
        """
        Returns a numpy array consisting of all velocities at the given indices

        Parameters
        ----------
        frame_indices : list of int
            momenta indices to be loaded
        atom_indices : list of int
            selects only the atoms to be returned. If None (Default) all atoms
            will be selected


        Returns
        -------
        numpy.ndarray, shape = (l,n)
            returns an array with `l` the number of frames and `n` the number
            of atoms
        """

        return self.velocities_as_numpy(frame_indices, atom_indices)

    def _init(self):
        """
        Initializes the associated storage to index momentums in it
        """

        super(MomentumStore, self)._init()

        n_atoms = self.storage.n_atoms
        n_spatial = self.storage.n_spatial

        snapshot = self.storage.template

        unit = None

        if snapshot.coordinates is not None:
            if hasattr(snapshot.coordinates, 'unit'):
                unit = snapshot.coordinates.unit

        self.create_variable('velocities', 'numpy.float32',
                           dimensions=('atom', 'spatial'),
                           description="the velocity of atom 'atom' in dimension " +
                                       "'coordinate' of momentum 'momentum'.",
                           chunksizes=(1, n_atoms, n_spatial),
                           simtk_unit=unit
                           )