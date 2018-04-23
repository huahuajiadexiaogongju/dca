import numpy as np

from strats.base import RLStrat
from utils import prod


class QTable(RLStrat):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alpha = self.pp['alpha']
        self.alpha_decay = self.pp['alpha_decay']
        self.lmbda = self.pp['lambda']
        if self.lmbda is not None:
            self.logger.error("Using lambda returns")

    def load_qvals(self):
        """Load Q-values from file"""
        fname = self.pp['restore_qtable']
        if fname != '':
            self.qvals = np.load(fname)
            self.logger.error(f"Restored qvals from {fname}")

    def fn_after(self):
        self.logger.info(f"Max qval: {np.max(self.qvals)}")
        if self.save:
            fname = "qtable"
            self.logger.error(f"Saved Q-table to {fname}.npy")
            np.save(fname, self.qvals)

    def get_qvals(self, cell, n_used, chs=None, *args, **kwargs):
        rep = self.feature_rep(cell, n_used)
        if chs is None:
            return self.qvals[rep]
        else:
            return self.qvals[rep][chs]

    def update_qval(self, grid, cell, ch, reward, next_cell, next_ch, next_max_ch,
                    discount, p):
        assert type(ch) == np.int64
        assert ch is not None
        if self.pp['verify_grid']:
            assert np.sum(grid != self.grid) == 1
        next_n_used = np.count_nonzero(self.grid[next_cell])
        next_qval = self.get_qvals(next_cell, next_n_used, next_ch)
        target_q = reward + discount * next_qval
        # Counting n_used of self.grid instead of grid yields significantly lower
        # blockprob on (TT-)SARSA for unknown reasons.
        n_used = np.count_nonzero(grid[cell])
        q = self.get_qvals(cell, n_used, ch)
        self.qval_means.append(np.mean(self.get_qvals(cell, n_used)))
        td_err = target_q - q
        self.losses.append(td_err**2)
        frep = self.feature_rep(cell, n_used)
        if self.lmbda is None:
            self.qvals[frep][ch] += self.alpha * td_err
        else:
            self.el_traces[frep][ch] += 1
            self.qvals += self.alpha * td_err * self.el_traces
            self.el_traces *= discount * self.lmbda
        if self.alpha > self.pp['min_alpha']:
            self.alpha *= self.alpha_decay
        next_frep = self.feature_rep(next_cell, next_n_used)
        self.logger.debug(
            f"Q[{frep}][{ch}]:{q:.1f} -> {reward:.1f} + Q[{next_frep}][{next_ch}]:{next_qval:.1f}"
        )


class SARSA(QTable):
    """
    State consists of cell coordinates and the number of used channels in that cell.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # "qvals[r, c, n_used, ch] = v"
        # Assigning channel 'ch' to the cell at row 'r', col 'c'
        # has q-value 'v' given that 'n_used' channels are already
        # in use at that cell.
        self.qvals = np.zeros(
            (self.rows, self.cols, self.n_channels, self.n_channels), dtype=np.float32)
        self.load_qvals()
        if self.lmbda is not None:
            # Eligibility traces
            self.el_traces = np.zeros(self.dims)

    def feature_rep(self, cell, n_used):
        return (*cell, n_used)


class TT_SARSA(QTable):
    """
    Table-trimmed SARSA.
    State consists of cell coordinates and the number of used channels.
    States where the number of used channels is or exceeds 'k' have their values are
    aggregated to the state where the number of used channels is 'k-1'.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.k = 30
        self.qvals = np.zeros((self.rows, self.cols, self.k, self.n_channels))
        self.load_qvals()
        if self.lmbda is not None:
            # Eligibility traces
            self.el_traces = np.zeros((self.rows, self.cols, self._k, self.n_channels))

    def feature_rep(self, cell, n_used):
        return (*cell, min(self.k - 1, n_used))


class RS_SARSA(QTable):
    """
    Reduced-state SARSA.
    State consists of cell coordinates only.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.qvals = np.zeros(self.dims)
        self.load_qvals()
        if self.lmbda is not None:
            # Eligibility traces
            self.el_traces = np.zeros(self.dims)

    def feature_rep(self, cell, n_used):
        return cell


class NT_RS_SARSA(QTable):
    """
    No-target Reduced-state SARSA.
    State consists of cell coordinates only.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.qvals = np.zeros(self.dims)
        self.load_qvals()
        if self.lmbda is not None:
            # Eligibility traces
            self.el_traces = np.zeros(self.dims)

    def feature_rep(self, cell, n_used):
        return cell

    def update_qval(self, grid, cell, ch, reward, next_cell, next_ch, next_max_ch,
                    discount):
        assert type(ch) == np.int64
        assert ch is not None
        self.qval_means.append(np.mean(self.qvals[cell]))
        td_err = (reward - self.qvals[cell][ch])
        self.losses.append(td_err**2)
        self.qvals[cell][ch] += self.alpha * td_err
        self.alpha *= self.alpha_decay


class E_RS_SARSA(QTable):
    """
    Expected Reduced-state SARSA.
    State consists of cell coordinates only.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.qvals = np.zeros(self.dims)
        self.load_qvals()

    def feature_rep(self, cell, n_used):
        return cell

    def update_qval(self, grid, cell, ch, reward, next_cell, next_ch, next_max_ch,
                    discount):
        assert type(ch) == np.int64
        assert ch is not None
        next_n_used = np.count_nonzero(self.grid[next_cell])
        next_qvals = self.get_qvals(next_cell, next_n_used)
        scaled = np.exp((next_qvals - np.max(next_qvals)) / self.epsilon)
        probs = scaled / np.sum(scaled)
        expected_next_q = np.sum(probs * next_qvals)
        target_q = reward + discount * expected_next_q

        n_used = np.count_nonzero(grid[cell])
        q = self.get_qvals(cell, n_used, ch)
        td_err = target_q - q
        self.losses.append(td_err**2)

        frep = self.feature_rep(cell, n_used)
        self.qvals[frep][ch] += self.alpha * td_err
        if self.alpha > self.pp['min_alpha']:
            self.alpha *= self.alpha_decay


class ZapQ(RLStrat):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alpha = self.pp['alpha']
        self.alpha_decay = self.pp['alpha_decay']
        # State-action pair numbers
        self.d = prod(self.dims)
        self.qvals = np.zeros(self.d)
        self.sa_nums = np.arange(self.d).reshape(self.dims)
        self.azap = np.zeros((self.d, self.d))

    def fn_after(self):
        self.logger.info(f"Max qval: {np.max(self.qvals)}")

    def get_qvals(self, cell, n_used=None, chs=None, *args, **kwargs):
        if chs is None or type(chs) is list:
            raise NotImplementedError(chs)
        else:
            return self.qvals[self.sa_nums[cell][chs]]

    def update_qval(self, grid, cell, ch, reward, next_cell, next_ch, next_max_ch,
                    discount, p):
        assert type(ch) == np.int64
        assert ch is not None
        assert next_max_ch is not None

        sa_num = self.sa_nums[cell][ch]
        next_sa_num = self.sa_nums[next_cell][next_max_ch]
        outer1 = np.zeros((self.d, self.d))
        outer2 = np.zeros((self.d, self.d))
        outer1[sa_num, sa_num] = 1
        outer2[sa_num, next_sa_num] = 1

        azap_gam = np.power((self.i + 1), -0.85)  # stepsize for matrix gain recursion
        self.azap += azap_gam * ((-outer1 + discount * outer2) - self.azap)
        azap_inv = np.linalg.pinv(self.azap)
        a_inv_dot = azap_inv[:, sa_num]

        q = self.get_qvals(cell, chs=ch)
        next_q = self.get_qvals(next_cell, chs=next_max_ch)
        td_err = reward + discount * next_q - q
        self.qvals -= self.alpha * a_inv_dot * td_err

        self.losses.append(td_err**2)
        self.alpha *= self.alpha_decay
