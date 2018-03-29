import numpy as np
import tensorflow as tf
import tensorflow.contrib.keras as k  # noqa

from nets.convlayers import InPlaneSplit, SeparableSplit
from nets.net import Net
from nets.utils import get_trainable_vars, prep_data_grids

from nets.convlayers import InPlaneSplitLocallyConnected2D  # noqa; noqa


class SinghNet(Net):
    def __init__(self, pp, logger, big_freps=False):
        """
        Afterstate value net
        """
        self.name = "SinghNet"
        self.pre_conv = pp['pre_conv']
        self.grid_inp = pp['singh_grid']
        self.depth = 3 * 70 + 1 if big_freps else 70 + 1
        self.frepshape = [pp['rows'], pp['cols'], self.depth]
        super().__init__(name=self.name, pp=pp, logger=logger)

    def _build_net(self, inp, name):
        with tf.variable_scope('model/' + name) as scope:
            if self.pre_conv:
                print(inp.shape)
                # [filter_height, filter_width, in_channels, channel_multiplier]
                # filters = tf.Variable(tf.ones((3, 3, self.depth, 1)) * 0.1)
                # conv = tf.nn.depthwise_conv2d(
                #     inp, filters, strides=[1, 1, 1, 1], padding='SAME')
                # dense_inp = tf.nn.relu(conv)

                dense_inp = SeparableSplit(
                    kernel_size=3, stride=1, use_bias=False, padding="VALID").apply(
                        inp, True)
                # c1 = InPlaneSplit(
                #     kernel_size=3, stride=1, use_bias=False, padding="VALID").apply(
                #         inp, False)
                # dense_inp = InPlaneSplit(
                #     kernel_size=3, stride=1, use_bias=False, padding="VALID").apply(
                #         c1, True)

                # lconv = k.layers.LocallyConnected2D(filters=70, kernel_size=3)
                # dense_inp = lconv(inp)

                # dense_inp = self.add_conv_layer(inp, 70, 3, padding="same", use_bias=False)
                # dense_inp = self.add_conv_layer(conv1, 3 * 70, 3)
                # TODO: Try with bias
                # pad = tf.keras.layers.ZeroPadding2D((1, 1))
                # out = pad(inp)
                # inplane_loc = InPlaneSplitLocallyConnected2D(
                #     kernel_size=[3, 3],
                #     strides=[3, 3],
                #     activation=tf.nn.relu,
                #     kernel_initializer=tf.constant_initializer(0.1))
                # self.dense_inp = dense_inp = inplane_loc(inp)
                print(dense_inp.shape)
            else:
                dense_inp = inp
            value_layer = tf.layers.Dense(
                units=1,
                # kernel_initializer=tf.zeros_initializer(),
                kernel_initializer=self.kern_init_dense(),
                kernel_regularizer=self.dense_regularizer,
                use_bias=False,
                activation=None)
            value = value_layer.apply(tf.layers.flatten(dense_inp))
            self.weight_vars.append(value_layer.kernel)
            self.weight_names.append(value_layer.name)
            trainable_vars = get_trainable_vars(scope)
        return value, trainable_vars

    def build(self):
        self.freps = tf.placeholder(tf.int32, [None, *self.frepshape], "feature_reps")
        self.grids = tf.placeholder(
            tf.bool, [None, self.rows, self.cols, 2 * self.n_channels], "grid")
        self.value_target = tf.placeholder(tf.float32, [None, 1], "value_target")
        self.weights = tf.placeholder(tf.float32, [None, 1], "weight")

        freps = tf.cast(self.freps, tf.float32)
        if self.grid_inp:
            net_inp = tf.concat([tf.cast(self.grids, tf.float32), freps], axis=3)
        else:
            net_inp = freps
        self.value, online_vars = self._build_net(net_inp, "online")

        self.err = self.value_target - self.value
        if self.pp['huber_loss'] is not None:
            # Linear when loss is above delta and squared difference below
            self.loss = tf.losses.huber_loss(
                labels=self.value_target,
                predictions=self.value,
                delta=self.pp['huber_loss'])
        else:
            self.loss = tf.losses.mean_squared_error(
                labels=self.value_target, predictions=self.value, weights=self.weights)
        return self.loss, online_vars

    def forward(self, freps, grids=None):
        data = {
            self.freps: freps,
        }
        if self.grid_inp:
            data[self.grids] = prep_data_grids(grids, self.grid_split)
        values = self.sess.run(
            self.value, data, options=self.options, run_metadata=self.run_metadata)
        vals = np.reshape(values, [-1])
        return vals

    def backward_supervised(self,
                            freps,
                            value_target,
                            weights=[1],
                            grids=None,
                            *args,
                            **kwargs):
        weights = np.expand_dims(weights, axis=1)
        data = {self.freps: freps, self.value_target: value_target, self.weights: weights}
        if self.grid_inp:
            data[self.grids] = prep_data_grids(grids, self.grid_split)
        _, loss, lr, err = self.sess.run(
            [self.do_train, self.loss, self.lr, self.err],
            feed_dict=data,
            options=self.options,
            run_metadata=self.run_metadata)
        return loss, lr, err

    def backward(self,
                 freps,
                 rewards,
                 next_freps,
                 grids=None,
                 next_grids=None,
                 discount=None,
                 weights=[1]):
        data = {self.freps: next_freps}
        if self.grid_inp:
            data[self.grids] = prep_data_grids(next_grids, self.grid_split)
        next_value = self.sess.run(self.value, data)
        # print(next_value, next_value.shape)
        rewards = np.expand_dims(rewards, axis=1)
        value_target = rewards + discount * next_value
        # print(value_target, value_target.shape, rewards)
        return self.backward_supervised(grids, freps, value_target, weights)
