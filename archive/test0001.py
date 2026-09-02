import env

import numpy as np
import gym

from keras.models import Sequential
from keras.layers import Dense, Activation, Flatten
from keras.optimizers import Adam

from rl.agents.dqn import DQNAgent
from rl.policy import BoltzmannQPolicy
from rl.memory import SequentialMemory

ENV_NAME = 'timetable-case0001-v0001'

# Get the environment and extract the number of actions.
env = gym.make(ENV_NAME)
def test(env):
    action = env.action_space.sample()
    obs, r, done, info = env.step(action)
    env.render()
    print('action:', action)
    print('reward:', r)
    print('done:', done)
    print('info:', info)
    print('nb_actions', env.action_space.n)

test(env)
test(env)
test(env)
test(env)
test(env)