import signal
from typing import Tuple

import numpy as np

from environment import Env
from eventgen import CEvent
from grid import RhombusAxialGrid
from replaybuffer import ReplayBuffer


class Strat:
    def __init__(self, pp, logger, pid="", gui=None, *args, **kwargs):
        self.rows = pp['rows']
        self.cols = pp['cols']
        self.n_channels = pp['n_channels']
        self.dims = pp['dims']
        self.save = pp['save_exp_data']
        self.batch_size = pp['batch_size']
        self.pp = pp
        self.logger = logger

        grid = RhombusAxialGrid(*self.dims, self.logger)
        self.env = Env(self.pp, grid, self.logger, pid)
        self.grid = self.env.grid.state
        self.replaybuffer = ReplayBuffer(pp['buffer_size'], *self.dims)

        self.quit_sim = False
        self.net = None
        signal.signal(signal.SIGINT, self.exit_handler)

    def exit_handler(self, *args):
        """
        Graceful exit on ctrl-c signal from
        command line or on 'q' key-event from gui.
        """
        self.logger.error("\nPremature exit")
        self.quit_sim = True
        if self.net is not None:
            self.net.quit_sim = True

    def simulate(self) -> Tuple[float, float]:
        """
        Run simulation and return a tuple with cumulative call
        block probability and cumulative handoff block probability
        """
        cevent = self.env.init_calls()
        ch = self.get_init_action(cevent)

        # Discrete event simulation
        i, t = 0, 0
        while self.continue_sim(i, t):
            if self.quit_sim:
                break  # Gracefully exit to print stats, clean up etc.

            t, ce_type, cell = cevent[0:3]
            grid = np.copy(self.grid)  # Copy before state is modified
            reward, next_cevent = self.env.step(ch)
            next_ch = self.get_action(next_cevent, grid, cell, ch, reward, ce_type)
            if (self.save or self.batch_size > 1) \
                    and ch is not None \
                    and next_ch is not None \
                    and ce_type != CEvent.END:
                # Only add (s, a, r, s', a') tuples for which the events in
                # s is not an END events, and for which there is an
                # available action a.
                # If there is no available action, that is, there are no
                # free channels which to assign, the neural net is not used
                # for selection and so it should not be trained on that data.
                # END events are not trained on either because the network is
                # supposed to predict the q-values for different channel
                # assignments; however the channels available for reassignment
                # are always busy in a grid corresponding to an END event.
                next_grid = np.copy(self.grid)
                next_cell = next_cevent[2]
                self.replaybuffer.add(grid, cell, ch, reward, next_grid, next_cell)

            if i > 0:
                if i % self.pp['log_iter'] == 0:
                    self.fn_report()
                if self.pp['net'] and \
                        i % self.net_copy_iter == 0:
                    self.update_target_net()
                if self.pp['net_copy_iter_decr'] and \
                   i % self.pp['net_copy_iter_decr'] == 0 and \
                   self.net_copy_iter > 1:
                    self.net_copy_iter -= 1
                    self.logger.info(f"Decreased net copy iter to {self.net_copy_iter}")
            ch, cevent = next_ch, next_cevent
            i += 1
        self.env.stats.end_episode(np.count_nonzero(self.grid))
        self.fn_after()
        if self.save:
            self.replaybuffer.save_experience_to_disk()
        if self.quit_sim and (self.pp['hopt'] or self.pp['avg_runs']):
            # Don't want to return actual block prob for incomplete sims when
            # optimizing params, because block prob is much lower at sim start
            return (1.0, 1.0)
        return (self.env.stats.block_prob_cum, self.env.stats.block_prob_cum_hoff)

    def continue_sim(self, i, t) -> bool:
        if self.pp['n_hours'] is not None:
            return (t / 60) < self.pp['n_hours']
        else:
            return i < self.pp['n_events']

    def get_init_action(self, next_cevent) -> int:
        """Return a channel to be (re)assigned in response to 'next_cevent'."""
        raise NotImplementedError

    def get_action(self, next_cevent, grid, cell, ch, reward, ce_type) -> int:
        """Return a channel to be (re)assigned in response to 'next_cevent'.

        'cell' and 'ch' specify the action that was previously executed on
        'grid' in response to an event of type 'ce_type', resulting in
        'reward'.
        """
        raise NotImplementedError

    def fn_report(self):
        """
        Report stats for different strategies
        """
        pass

    def fn_after(self):
        """
        Cleanup after simulation
        """
        pass


class RLStrat(Strat):
    def __init__(self, pp, *args, **kwargs):
        super().__init__(pp, *args, **kwargs)
        self.epsilon = pp['epsilon']
        self.epsilon_decay = pp['epsilon_decay']
        self.alpha = pp['alpha']
        self.alpha_decay = pp['alpha_decay']
        self.gamma = pp['gamma']
        self.logger.info(f"NP Rand: {np.random.uniform()}")

    def fn_report(self):
        self.env.stats.report_rl(self.epsilon, self.alpha)

    # def fn_after(self):
    #     self.logger.info(f"NP Rand: {np.random.uniform()}")

    def get_init_action(self, cevent):
        ch, _, = self.optimal_ch(ce_type=cevent[1], cell=cevent[2])
        return ch

    def get_action(self, next_cevent, grid, cell, ch, reward, ce_type) -> int:
        next_ce_type, next_cell = next_cevent[1:3]
        # Choose A' from S'
        next_ch, next_max_ch = self.optimal_ch(next_ce_type, next_cell)
        # If there's no action to take, or no action was taken,
        # don't update q-value at all
        if ce_type != CEvent.END and  \
           ch is not None and next_ch is not None:
            # Observe reward from previous action, and
            # update q-values with one-step lookahead
            self.update_qval(grid, cell, ch, reward, next_cell, next_ch, next_max_ch)
        return next_ch

    def policy_eps_greedy(self, chs, qvals_sparse):
        """Epsilon greedy action selection with expontential decay"""
        if np.random.random() < self.epsilon:
            # Choose an eligible channel at random
            ch = np.random.choice(chs)
        else:
            # Choose greedily
            idx = np.argmax(qvals_sparse)
            ch = chs[idx]
        self.epsilon *= self.epsilon_decay  # Epsilon decay
        return ch

    def policy_boltzmann(self, chs, qvals_sparse):
        scaled = np.exp((qvals_sparse - np.max(qvals_sparse)) / self.temp)
        probs = scaled / np.sum(scaled)
        ch = np.random.choice(chs, p=probs)
        return ch

    def optimal_ch(self, ce_type, cell) -> Tuple[int, float, int]:
        """Select the channel fitting for assignment that
        that has the maximum q-value according to an exploration policy,
        or select the channel for termination that has the minimum
        q-value in a greedy fashion.

        Return (ch, max_ch) where 'ch' is the selected channel according to
        exploration policy and max_ch' is the greedy (still eligible) channel.
        'ch' (and 'max_ch') is None if no channel is eligible for assignment.
        """
        inuse = np.nonzero(self.grid[cell])[0]
        n_used = len(inuse)

        if ce_type == CEvent.NEW or ce_type == CEvent.HOFF:
            chs = self.env.grid.get_eligible_chs(cell)
            if len(chs) == 0:
                # No channels available for assignment,
                return (None, None)
        else:
            # Channels in use at cell, including channel scheduled
            # for termination. The latter is included because it might
            # be the least valueable channel, in which case no
            # reassignment is done on call termination.
            chs = inuse
            # or no channels in use to reassign
            assert n_used > 0

        # TODO If 'max_ch' turns out not to be useful, then don't return it and
        # avoid running a forward pass through the net if a random action is selected.
        qvals_sparse = self.get_qvals(cell=cell, n_used=n_used, ce_type=ce_type, chs=chs)
        # Selecting a ch for reassigment is always greedy because no learning
        # is done on the reassignment actions.
        if ce_type == CEvent.END:
            amin_idx = np.argmin(qvals_sparse)
            ch = chs[amin_idx]
            max_ch = ch
        else:
            # print(qvals_sparse.shape, chs.shape)
            ch = self.policy_eps_greedy(chs, qvals_sparse)
            amax_idx = np.argmax(qvals_sparse)
            max_ch = chs[amax_idx]

        # If qvals blow up ('NaN's and 'inf's), ch becomes none.
        if ch is None:
            self.logger.error(f"ch is none for {ce_type}\n{chs}\n{qvals_sparse}\n")
            raise Exception
        self.logger.debug(f"Optimal ch: {ch} for event {ce_type} of possibilities {chs}")
        return (ch, max_ch)