import os
import sys
from time import time

import numpy as np
import tensorflow as tf
from matplotlib import pyplot as plt
from tensorflow.python.client import timeline

import datahandler
from grid import Grid  # noqa
from nets.utils import (build_default_trainer, get_act_fn_by_name,
                        get_init_by_name)

MAX_CPU_PROCS = 4
"""
Perhaps reducing call rates will increase difference between
fixed/random and a good alg, thus making testing nets easier.
If so then need to retest sarsa-strats and redo hyperparam opt.
"""


class Net:
    def __init__(self, pp, logger, name):
        self.logger = logger
        self.save = pp['save_net']
        restore = pp['restore_net']
        self.gamma = pp['gamma']
        self.batch_size = pp['batch_size']
        self.n_channels = pp['n_channels']
        self.pp = pp
        main_path = "model/" + name
        self.model_path = main_path + "/model.cpkt"
        self.log_path = main_path + "/logs"
        self.quit_sim = False

        # self.neighs_mask = tf.constant(Grid.neighbors_all_oh(), dtype=tf.bool)
        self.act_fn = get_act_fn_by_name(pp['act_fn'])
        self.kern_init_conv = get_init_by_name(pp['weight_init_conv'])
        self.kern_init_dense = get_init_by_name(pp['weight_init_dense'])
        self.regularizer = None
        if pp['layer_norm']:
            self.regularizer = tf.contrib.layers.layer_norm

        tf.reset_default_graph()
        self.options = None
        self.run_metadata = None
        if pp['tfprofiling']:
            self.options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
            self.run_metadata = tf.RunMetadata()
        # tf.logging.set_verbosity(tf.logging.WARN)

        gpu_procs = int(os.environ.get("GPU_PROCS", "0"))
        if pp['no_gpu'] or gpu_procs > MAX_CPU_PROCS:
            self.logger.error("Not using GPU")
            self.using_gpu = False
            config = tf.ConfigProto(device_count={'GPU': 0})
        else:
            os.environ['GPU_PROCS'] = str(gpu_procs + 1)
            self.using_gpu = True
            config = tf.ConfigProto()
        # config.intra_opt_parallelism_threads = 4
        # Allocate only minimum amount necessary GPU memory at start, then grow
        config.gpu_options.allow_growth = True
        tf.set_random_seed(pp['rng_seed'])
        self.sess = tf.Session(config=config)

        trainable_vars = self.build()
        glob_vars = set(tf.global_variables())
        if self.save or restore:
            self.saver = tf.train.Saver(
                var_list=tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='model'))
        self.sess.run(tf.global_variables_initializer())
        if restore:
            # Could do a try/except and build if loading fails
            self.logger.error(f"Restoring model from {self.model_path}")
            self.saver.restore(self.sess, self.model_path)
        self.do_train, self.lr = build_default_trainer(pp, self.loss, trainable_vars)
        self.sess.run(tf.variables_initializer(set(tf.global_variables()) - glob_vars))
        self.data_is_loaded = False

    def build(self):
        raise NotImplementedError

    def forward(self):
        raise NotImplementedError

    def backward(self):
        raise NotImplementedError

    def close(self):
        self.net.save_timeline()
        self.net.sess.close()
        if self.using_gpu:
            gpu_procs = int(os.environ.get("GPU_PROCS", "0"))
            assert gpu_procs > 0
            os.environ['GPU_PROCS'] = str(gpu_procs - 1)

    def _build_base_net(self, grid, cell, name):
        with tf.variable_scope('model/' + name):
            conv1 = tf.layers.conv2d(
                inputs=grid,
                filters=self.n_channels,
                kernel_size=4,
                padding="same",
                kernel_initializer=self.kern_init_conv(),
                kernel_regularizer=self.regularizer,
                use_bias=True,  # Default setting
                activation=self.act_fn)
            conv2 = tf.layers.conv2d(
                inputs=conv1,
                filters=70,
                kernel_size=3,
                padding="same",
                kernel_initializer=self.kern_init_conv(),
                kernel_regularizer=self.regularizer,
                use_bias=True,
                activation=self.act_fn)
            stacked = tf.concat([conv2, cell], axis=3)
            flat = tf.layers.flatten(stacked)
            return flat

    def load_data(self):
        if self.data_is_loaded:
            return
        data = datahandler.get_data_h5py(self.batch_size)
        self.n_train_steps = data['n_train_steps']
        self.n_test_steps = data['n_test_steps']
        self.train_gen = data['train_gen']
        self.test_gen = data['test_gen']
        self.qvals = np.load("qtable.npy")
        self.data_is_loaded = True

    def save_model(self):
        inp = ""
        path = n_path = self.model_path
        if os.path.isdir(path + ".index"):
            while inp not in ["Y", "N", "A"]:
                inp = input("A model exists in {path}. Overwrite (Y), Don't save (N), "
                            "or Save to directory (A): ").upper()
            if inp == "A":
                i = 0
                while os.path.isdir(n_path):
                    n_path = path + str(i)
                    i += 1
        if inp not in ["N"]:
            self.logger.error(f"Saving model to path {n_path}")
            self.saver.save(self.sess, n_path)

    def save_timeline(self):
        if self.pp['tfprofiling']:
            fetched_timeline = timeline.Timeline(self.run_metadata.step_stats)
            chrome_trace = fetched_timeline.generate_chrome_trace_format()
            with open(self.pp['tfprofiling'], 'w') as f:
                f.write(chrome_trace)

    def train(self):
        self.load_data()
        losses = []
        self.logger.warn(f"Training {self.n_train_steps} minibatches of size"
                         f" {self.batch_size} for a total of"
                         f" {self.n_train_steps * self.batch_size} examples")
        for i in range(self.n_train_steps):
            data = next(self.train_gen)
            cells = data['cells']
            targets = np.zeros(len(cells), dtype=np.float32)
            actions = data['actions']
            for j, ch in enumerate(actions):
                targets[j] = self.qvals[cells[j]][ch]
            _, loss = self.backward(**data)
            if i % 50 == 0:
                # tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
                # run_metadata = tf.RunMetadata()
                # self.train_writer.add_run_metadata(
                #     run_metadata, 'step%d' % i)
                self.logger.info(f"Iter {i}\tloss: {loss:.2f}")
                losses.append(loss)
            if False:
                self.logger.debug(f"grid: {data['grids'][0]} \n"
                                  f"cell: {data['cells'][0]} \n"
                                  f"oh_cell: {data['oh_cells'][0]} \n"
                                  f"action: {data['actions'][0]} \n"
                                  f"reward: {data['rewards'][0]} \n"
                                  f"target: {targets[0]} \n"
                                  f"loss: {loss} \n")
                sys.exit(0)
            if np.isnan(loss) or np.isinf(loss):
                self.logger.error(f"Invalid loss: {loss}")
                sys.exit(0)
                break
            if self.quit_sim:
                sys.exit(0)
        if self.save:
            self.save_model()
        plt.plot(losses)
        plt.ylabel("Loss")
        plt.xlabel(f"Iterations, in {self.batch_size}s")
        plt.show()

    def bench_batch_size(self):
        for bs in [256, 512, 1024, 2048]:
            self.pp['batch_size'] = bs
            t = time.time()
            self.train()
            self.logger.error(f"Batch size {bs} took {time.time()-t:.2f} seconds")

    def rand_uniform(self):
        """Used for checking if random seeds are set/working"""
        r = tf.random_uniform([1])
        ra = self.sess.run(r)
        return ra

    def inuse_qvals(self, grids, cells, qvals):
        """
        Tested and works, but slower than CPU

        Return a dense array of q-values that are in use

        Expects:
        grids.shape: [None, 7, 7, 70/140]
        cells.shape: [None, 2]
        qvals.shape: [None, 70]
        """
        arange = tf.expand_dims(tf.range(tf.shape(cells)[0]), axis=1)
        rcells = tf.concat([arange, cells], axis=1)
        alloc_maps = tf.gather_nd(grids[:, :, :, :70], rcells)
        inuse_qvals = tf.cast(alloc_maps, tf.float32) * qvals
        return inuse_qvals

    def eligible_qvals(self, grids, cells, qvals):
        """
        Tested and works, but slower than CPU

        Return a dense array of q-values that are eligible to assignment
        without violating the reuse constraint

        Expects:
        grids.shape: [None, 7, 7, 70/140]
        cells.shape: [None, 2]
        qvals.shape: [None, 70]
        """

        def get_elig_alloc_map(inp):
            # inp.shape: (7, 7, 71)
            grid = inp[:, :, :70]
            neighs_mask_local = inp[:, :, -1]
            # Code below here needs to be mapped because 'where' will produce
            # variable length result
            neighs_i = tf.where(neighs_mask_local)
            neighs = tf.gather_nd(grid, neighs_i)
            alloc_map = tf.reduce_any(neighs, axis=0)
            # Can't return elig chs because variable length result
            # eligible_chs = tf.reshape(tf.where(tf.logical_not(alloc_map)), [-1])
            return alloc_map

        neighs_mask_local = tf.gather_nd(self.neighs_mask, cells)
        inp = tf.concat([grids, tf.expand_dims(neighs_mask_local, axis=3)], axis=3)
        alloc_maps = tf.map_fn(get_elig_alloc_map, inp, dtype=tf.bool)
        # TODO This should be sparse instead, allowing for multiple grids
        # in forward batch or for this method to be used in a backward pass
        # elig_qvals = tf.boolean_mask(qvals, tf.logical_not(alloc_maps))
        elig_qvals = tf.cast(tf.logical_not(alloc_maps), tf.float32) * qvals
        return elig_qvals


if __name__ == "__main__":
    import logging
    logger = logging.getLogger('')
    n = Net(logger)
    n.train()
