from enum import Enum
import math
import functools

import numpy as np


class Direction(Enum):
    NE = 0
    SE = 1
    S = 2
    SW = 3
    NW = 4
    N = 5


class Grid:
    def __init__(self, rows, cols, n_channels, logger,
                 *args, **kwargs):
        self.rows = rows
        self.cols = cols
        self.n_channels = n_channels
        self.logger = logger

        self.state = np.zeros(
            (self.rows, self.cols, self.n_channels), dtype=bool)
        self.labels = np.zeros((self.rows, self.cols), dtype=int)
        self._partition_cells()

    def print_cell(self, r, c):
        print(np.where(self.state[r][c] == 1))

    def print_neighs2(self, row, col):
        """
        Show all the channels for the given cell and its neighbors
        """
        print(f"\n{row}, {col}: {np.where(self.state[row][col]==1)}")
        for neigh in self.neighbors2(row, col):
            print(
                f"\n{neigh}: {np.where(self.state[neigh]==1)}")

    def __str__(self):
        strstate = ""
        for r in range(self.rows):
            for c in range(self.cols):
                inuse = np.where(self.state[r][c] == 1)
                strstate += f"\n({r},{c}): {len(inuse)} used - {inuse}"
        return strstate

    def validate_reuse_constr(self):
        """
        Verify that the channel reuse constraint of 3 is not violated,
        e.g. that a channel in use in a cell is not in use in its neighbors.
        Returns True if valid not violated, False otherwise
        """
        # TODO: It might be possible to do this more efficiently.
        # If no neighbors of a cell violate the channel reuse constraint,
        # then the cell itself does not either, so it should be possible
        # to skip checking some cells.
        for r in range(self.rows):
            for c in range(self.cols):
                neighs = self.neighbors2(r, c, True)
                # Channels in use at neighbors
                inuse = np.bitwise_or.reduce(self.state[neighs])
                # Channels in use at a neigh and cell
                inuse_both = np.bitwise_and(self.state[r][c], inuse)
                viols = np.where(inuse_both == 1)[0]
                if len(viols) > 0:
                    self.logger.error("Channel Reuse constraint violated"
                                      f" in Cell {(r, c) }"
                                      f" at channels {viols}")
                    return False
        return True

    @staticmethod
    def move(row, col, direction):
        raise NotImplementedError
        f = None
        if direction == Direction.NE:
            f = Grid.move_n
        elif direction == Direction.SE:
            f = Grid.move_se
        elif direction == Direction.S:
            f = Grid.move_s
        elif direction == Direction.SW:
            f = Grid.move_sw
        elif direction == Direction.NW:
            f = Grid.move_nw
        elif direction == Direction.N:
            f = Grid.move_n
        return f(row, col)

    @staticmethod
    def direction(from_r, from_c, to_r, to_c):
        raise NotImplementedError
        if from_r - 1 == to_r and from_c == to_c:
            return Direction.N
        if from_r + 1 == to_r and from_c == to_c:
            return Direction.S
        if from_c % 2 == 0:
            if from_r == to_r and from_c + 1 == to_c:
                return Direction.NE
            if from_r + 1 == to_r and from_c + 1 == to_c:
                return Direction.SE
            if from_r + 1 == to_r and from_c - 1 == to_c:
                return Direction.SW
            if from_r == to_r and from_c - 1 == to_c:
                return Direction.NW
        else:
            if from_r - 1 == to_r and from_c + 1 == to_c:
                return Direction.NE
            if from_r == to_r and from_c + 1 == to_c:
                return Direction.SE
            if from_r == to_r and from_c - 1 == to_c:
                return Direction.SW
            if from_r - 1 == to_r and from_c - 1 == to_c:
                return Direction.NW

    @staticmethod
    def move_n(row, col):
        return (row - 1, col)

    @staticmethod
    def move_ne(row, col):
        if col % 2 == 0:
            return (row, col + 1)
        else:
            return (row - 1, col + 1)

    @staticmethod
    def move_se(row, col):
        if col % 2 == 0:
            return (row + 1, col + 1)
        else:
            return (row, col + 1)

    @staticmethod
    def move_s(row, col):
        return (row + 1, col)

    @staticmethod
    def move_sw(row, col):
        if col % 2 == 0:
            return (row + 1, col - 1)
        else:
            return (row, col - 1)

    @staticmethod
    def move_nw(row, col):
        if col % 2 == 0:
            return (row, col - 1)
        else:
            return (row - 1, col - 1)

    @staticmethod
    def neighbors1sparse(row, col):
        """
        Returns a list with indexes of neighbors within a radius of 1,
        not including self. The indexes may not be within grid.
        In clockwise order starting from north.
        """
        idxs = [
            Grid.move_n(row, col),
            Grid.move_ne(row, col),
            Grid.move_se(row, col),
            Grid.move_s(row, col),
            Grid.move_sw(row, col),
            Grid.move_nw(row, col)
        ]
        return idxs

    @functools.lru_cache(maxsize=None)
    def neighbors1(self, row, col):
        """
        Returns a list with indexes of neighbors within a radius of 1,
        not including self
        """
        idxs = []
        r_low = max(0, row - 1)
        r_hi = min(self.rows - 1, row + 1)
        c_low = max(0, col - 1)
        c_hi = min(self.cols - 1, col + 1)
        if col % 2 == 0:
            cross = row - 1
        else:
            cross = row + 1
        for r in range(r_low, r_hi + 1):
            for c in range(c_low, c_hi + 1):
                if not ((r, c) == (cross, col - 1) or
                        (r, c) == (cross, col + 1) or (r, c) == (row, col)):
                    idxs.append((r, c))
        return idxs

    @functools.lru_cache(maxsize=None)
    def neighbors2(self, row, col, separate=False):
        """
        If 'separate' is True, return ([r1, r2, ...], [c1, c2, ...]),
        else return [(r1, c1), (r2, c2), ...]

        Returns a list with indices of neighbors within a radius of 2,
        not including self
        """
        if separate:
            rs = []
            cs = []
        else:
            idxs = []

        r_low = max(0, row - 2)
        r_hi = min(self.rows - 1, row + 2)
        c_low = max(0, col - 2)
        c_hi = min(self.cols - 1, col + 2)
        if col % 2 == 0:
            cross1 = row - 2
            cross2 = row + 2
        else:
            cross1 = row + 2
            cross2 = row - 2
        for r in range(r_low, r_hi + 1):
            for c in range(c_low, c_hi + 1):
                if not ((r, c) == (row, col) or
                        (r, c) == (cross1, col - 2) or
                        (r, c) == (cross1, col - 1) or
                        (r, c) == (cross1, col + 1) or
                        (r, c) == (cross1, col + 2) or
                        (r, c) == (cross2, col - 2) or
                        (r, c) == (cross2, col + 2)):
                    if separate:
                        rs.append(r)
                        cs.append(c)
                    else:
                        idxs.append((r, c))

        # k = self.rows
        # idxs2all = np.array(
        #     np.meshgrid(np.arange(k), np.arange(k), indexing="ij")) \
        #     .transpose([1, 2, 0]) \
        #     .reshape(1, -2, 2)[0}
        if separate:
            return (rs, cs)
        else:
            return idxs

    def neighbors2all(self):
        # NOTE the results, i.e. np.arrays, do NOT
        # index the same way as tuples
        neighs2 = np.zeros((self.rows, self.cols, 18, 2), dtype=np.int32)
        mask = np.zeros((self.rows, self.cols, 18), dtype=np.bool)
        for row in range(self.rows):
            for col in range(self.cols):
                r_low = max(0, row - 2)
                r_hi = min(self.rows - 1, row + 2)
                c_low = max(0, col - 2)
                c_hi = min(self.cols - 1, col + 2)
                if col % 2 == 0:
                    cross1 = row - 2
                    cross2 = row + 2
                else:
                    cross1 = row + 2
                    cross2 = row - 2
                oh_idxs = np.zeros(
                    (self.rows + 2, self.cols + 2), dtype=np.bool)
                oh_idxs[r_low: r_hi + 1, c_low: c_hi + 1] = True

                oh_idxs[row, col] = False
                oh_idxs[cross1, col - 2] = False
                oh_idxs[cross1, col - 1] = False
                oh_idxs[cross1, col + 1] = False
                oh_idxs[cross1, col + 2] = False
                oh_idxs[cross2, col - 2] = False
                oh_idxs[cross2, col + 2] = False
                idxs = np.transpose(np.where(oh_idxs))
                neighs2[row][col][:idxs.shape[0], :idxs.shape[1]] = idxs
                mask[row][col][:idxs.shape[0]] = True
        return (neighs2, mask)

    def get_free_chs(self, cell):
        """
        Find the channels that are free in 'cell' and all of
        its neighbors by bitwise ORing all their allocation maps
        """
        neighs = self.neighbors2(*cell)
        alloc_map = np.bitwise_or(
            self.state[cell], self.state[neighs[0]])
        for n in neighs[1:]:
            alloc_map = np.bitwise_or(alloc_map, self.state[n])
        free = np.where(alloc_map == 0)[0]
        return free

    @staticmethod
    def distance(r1, c1, r2, c2):
        raise NotImplementedError
        if c1 % 2 == 0:
            if c2 % 2 == 0:
                distance = math.abs()
            else:
                pass
        else:
            if c2 % 2 == 0:
                pass
            else:
                pass
        return distance

    def _partition_cells(self):
        """
        Partition cells into 7 lots such that the minimum distance
        between cells with the same label ([0..6]) is at least 2
        (which corresponds to a minimum reuse distance of 3).

        Returns an n*m array with the label for each cell.
        """

        def right_up(x, y):
            x_new = x + 3
            y_new = y
            if x % 2 != 0:
                # Odd column
                y_new = y - 1
            return (x_new, y_new)

        def down_left(x, y):
            x_new = x - 1
            if x % 2 == 0:
                # Even column
                y_new = y + 3
            else:
                # Odd Column
                y_new = y + 2
            return (x_new, y_new)

        def label(l, x, y):
            # A center and some part of its subgrid may be out of bounds.
            if (x >= 0 and x < self.cols and y >= 0 and y < self.rows):
                self.labels[y][x] = l

        # Center of a 'circular' 7-cell subgrid in which
        # each cell has a unique label
        center = (0, 0)
        # First center in current row which has neighbors inside grid
        first_row_center = (0, 0)
        # Move center down-left until subgrid goes out of bounds
        while (center[0] >= -1) and (center[1] <= self.rows):
            # Move center right-up until subgrid goes out of bounds
            while (center[0] <= self.cols) and (center[1] >= -1):
                # Label cells 0..6 with given center as 0
                label(0, *center)
                for i, neigh in enumerate(
                        self.neighbors1sparse(center[1], center[0])):
                    label(i + 1, neigh[1], neigh[0])
                center = right_up(*center)
            center = down_left(*first_row_center)
            # Move right until x >= -1
            while center[0] < -1:
                center = right_up(*center)
            first_row_center = center


class ARGrid(Grid):
    "Rhombus grid with axial coordinates"
    def __init__(self, rows, cols, n_channels, logger,
                 *args, **kwargs):
        self.rows = rows
        self.cols = cols
        self.n_channels = n_channels
        self.logger = logger

        self.state = np.zeros(
            (self.rows, self.cols, self.n_channels), dtype=bool)

    @staticmethod
    def neighbors1sparse(row, col):
        """
        Returns a list with indexes of neighbors within a radius of 1,
        not including self. The indexes may not be within grid.
        In clockwise order starting from north.
        """
        raise NotImplementedError

    @functools.lru_cache(maxsize=None)
    def neighbors1(self, row, col):
        """
        Returns a list with indexes of neighbors within a radius of 1,
        not including self
        """
        idxs = []
        r_low = max(0, row - 1)
        r_hi = min(self.rows - 1, row + 1)
        c_low = max(0, col - 1)
        c_hi = min(self.cols - 1, col + 1)
        for r in range(r_low, r_hi + 1):
            for c in range(c_low, c_hi + 1):
                if not ((r, c) == (row - 1, col - 1) or
                        (r, c) == (col + 1, col + 1) or
                        (r, c) == (row, col)):
                    idxs.append((r, c))
        return idxs

    @functools.lru_cache(maxsize=None)
    def neighbors2(self, row, col):
        """
        If 'separate' is True, return ([r1, r2, ...], [c1, c2, ...]),
        else return [(r1, c1), (r2, c2), ...]

        Returns a list with indices of neighbors within a radius of 2,
        not including self
        """
        idxs = []

        r_low = max(0, row - 2)
        r_hi = min(self.rows - 1, row + 2)
        c_low = max(0, col - 2)
        c_hi = min(self.cols - 1, col + 2)
        for r in range(r_low, r_hi + 1):
            for c in range(c_low, c_hi + 1):
                if not ((r, c) == (row, col) or
                        (r, c) == (row - 2, col - 2) or
                        (r, c) == (row - 2, col - 1) or
                        (r, c) == (row - 1, col - 2) or
                        (r, c) == (row + 1, col + 2) or
                        (r, c) == (row + 2, col + 1) or
                        (r, c) == (row + 2, col + 2)):
                    idxs.append((r, c))
        return idxs

    def _partition_cells(self):
        # Perhaps super func still works
        raise NotImplementedError


class FixedGrid(Grid):
    def __init__(self, n_nom_channels=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Nominal channels for each cell
        self.nom_chs = np.zeros(
            (self.rows, self.cols, self.n_channels), dtype=bool)
        self.assign_chs(n_nom_channels)

    def assign_chs(self, n_nom_channels=0):
        """
        Partition the cells and channels up to and including 'n_channels'
        into 7 lots, and assign
        the channels to cells such that they will not interfere with each
        other within a channel reuse constraint of 3.
        The channels assigned to a cell are its nominal channels.

        Returns a (rows*cols*n_channels) array
        where a channel for a cell has value 1 if nominal, 0 otherwise.
        """
        if n_nom_channels == 0:
            n_channels = self.n_channels
        channels_per_subgrid_cell = []
        channels_per_subgrid_cell_accu = [0]
        channels_per_cell = n_channels / 7
        ceil = math.ceil(channels_per_cell)
        floor = math.floor(channels_per_cell)
        tot = 0
        for i in range(7):
            if tot + ceil + (6 - i) * floor > n_channels:
                tot += ceil
                cell_channels = ceil
            else:
                tot += floor
                cell_channels = floor
            channels_per_subgrid_cell.append(cell_channels)
            channels_per_subgrid_cell_accu.append(tot)
        for r in range(self.rows):
            for c in range(self.cols):
                label = self.labels[r][c]
                lo = channels_per_subgrid_cell_accu[label]
                hi = channels_per_subgrid_cell_accu[label + 1]
                self.nom_chs[r][c][lo:hi] = 1


class BDCLGrid(FixedGrid):
    def __init__(self, *args, **kwargs):
        raise NotImplementedError()
        super().__init__(*args, **kwargs)
        # For each channel, a direction is locked if entry is True
        self.locks = np.zeros(
            (self.rows, self.cols, self.n_channels, 7), dtype=bool)
        # A cell and a channel is locked by cell coordinates in entry
        # (-1, -1) if not locked.
        self.locked_by = np.zeros(
            (self.rows, self.cols, self.n_channels, 2), dtype=int)

    def cochannel_cells(self, cell, cell_neigh):
        """
        A cochannel cell of a cell 'c' given a neighbor 'b'
        is a cell with the same label as 'c' within a radius
        of 2 from 'b', i.e. the cells within the channel reuse distance
        of 3 when 'b' borrows a channel from 'c'.
        """
        raise NotImplementedError  # perhaps not implemented correctly
        neighs = self.neighbors2(*cell_neigh)
        coch_cells = []
        label = self.labels[cell]
        for neigh in neighs:
            if self.labels[cell_neigh] == label and neigh != cell:
                coch_cells.append(neigh)
        return coch_cells

    def borrow(self, from_cell, to_cell, ch):
        """
        Borrow a channel 'ch' from cell 'from' to cell 'to'.
        """
        # TODO implementation assumes borrowing allowed, i.e. does not
        # break any constraints or invariants
        coch_cells = self.cochannel_cells(*from_cell, *to_cell)
        for ccell in coch_cells:
            self.locked_by[ccell][ch] = [*to_cell]
        # Cochannel cells with their respective 1-radius neighbors
        coch_cells_wneighs = zip(coch_cells, map(self.neighbors1, coch_cells))
        to_cell_neighs = self.neighbors2(*to_cell)
        # Cells that would violate channel reuse constraint unless
        # locked from borrowing
        for (cc, ccn) in coch_cells_wneighs:
            for tcn in to_cell_neighs:
                if ccn == tcn:
                    for direction in Grid.direction(*cc, *ccn):
                        self.locks[cc][ch][direction] = 1
