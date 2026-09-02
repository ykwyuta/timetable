import sys

from collections import Counter
from io import StringIO
import numpy as np
import gym
import gym.spaces

class TimeTable (gym.Env):
  """
  -1 配置不可の枠
  0  未配置の枠
  1  現代文 毎日
  2  数学 毎日
  3  英語 毎日
  """
  
  CLASS_SIZE = 2
  
  WEEK_SIZE = 5
  
  DAY_SIZE = 3
  
  TIME_TABLE = np.zeros((CLASS_SIZE, WEEK_SIZE * DAY_SIZE))
  
  LESSON_LIST = [1] * 10 + [2] * 10 + [3] * 10
  
  MAX_DAMAGE = 100
  
  def __init__(self):
    super().__init__()
    self.action_space = gym.spaces.Discrete(2 * 5 * 3)
    self.observation_space = gym.spaces.Box(
        low = -1,
        high = max(self.LESSON_LIST),
        shape = self.TIME_TABLE.shape
    )
    self.reward_range = [0, len(self.LESSON_LIST)]
    self.reset()

  def reset(self):
    """
    状態を初期化し、初期の観測値を返す
    """
    self.damage = 0
    self.total = 0
    self.table = self.TIME_TABLE.copy()
    self.lesson = list(self.LESSON_LIST)
    return self.table.copy()
    
  def step(self, action):
    """
   1ステップ進める処理を記述。戻り値は observation, reward, done(ゲーム終了したか), info(追加の情報の辞書)
    """
    # 配置する授業を取り出す
    lesson = self.lesson.copy().pop()

    # 授業を配置することが可能化どうか
    if self._is_bookable(action, lesson):
      table = self.table.copy()
      shape = table.shape
      table = table.reshape(1, shape[0] * shape[1])
      table[0][action] = lesson
      self.table = table.reshape(shape)
      self.damage = 0
      self.lesson.pop()
      moved = True
    else:
      moved = False
    
    # いまの状態
    observation = self.table.copy()
    # 今回の移動によるダメージ
    self.damage += self._get_damage(moved)
    # 今回の移動による報酬
    reward = self._get_reward(moved)
    self.total += reward
    # 終了するか継続するかの判定
    self.done = self._is_done()
    return observation, reward, self.done, {}
  def _close(self):
    """
    [オプション]環境を閉じて後処理をする
    """
    pass
  def _seed(self, seed=None):
    """
    [オプション]ランダムシードを固定する
    """
    pass
  def _get_reward(self, moved):
    if moved:
      # 特典の計算。授業が分散されて配置できていると高得点になるようにしたいけど効率的な判定方法分からないので一旦スルー
      #       table = self.table.copy()
      #       shape = self.table.shape
      #       tableT = table.T
      #       # 授業のインデックスを集める
      #       lesson_index = dict([(lesson, []) for lesson in list(set(self.LESSON_LIST))])
      #       for i in range(shape[1]):
      #         for j in range(tableT[i])
      #           cell = tableT[i][j]
      #           lesson_index[cell].append(i)
      return len(self.LESSON_LIST) - len(self.lesson)
    else:
      # 配置できないところにコマを置こうとすると減点する
      return 0
  def _get_damage(self, moved):
    # 配置できないところにコマを置こうとすると減点する
    if moved:
      return 0
    else:
      return 1
  
  def _is_bookable(self, action, lesson):
    """
    授業を配置することが可能か否かを返す
    """
    table = self.table.copy()
    shape = self.table.shape
    table = table.reshape(1, shape[0] * shape[1])
    # 配置不可の枠には配置できない
    if table[0][action] == -1:
      return False
    # すでに配置済みのところには配置できない
    if table[0][action] > 0:
      return False
    # 更新をしてみる
    table[0][action] = lesson
    table = table.reshape(shape)
    tableT = table.T
    # 同じ時間帯に授業が入っていないかを確認する
    for i in range(shape[1]):
      row = tableT[i]
      count = Counter(row)
      if len([num for num in count.items() if num[0] > 0 and num[1] > 1]) > 0:
        return False
    # 1日に同じ授業は2回実施できない
    table = table.reshape(self.CLASS_SIZE, self.WEEK_SIZE, self.DAY_SIZE)
    for i in range(self.CLASS_SIZE):
      for j in range(self.WEEK_SIZE):
        row = table[i][j]
        count = Counter(row)
        if len([num for num in count.items() if num[0] > 0 and num[1] > 1]) > 0:
          return False
    return True 
  def _is_done(self):
    """
    すべての授業を配置するか、授業を配置できない状態がMAX_DAMAGE回続くと終了
    """
    if self.damage >= self.MAX_DAMAGE:
      return True
    elif len(self.lesson) == 0:
      self.render()
      sys.exit(0)
      return True
    return False
  
  def render(self, mode='human', close=False):
    """
    環境を可視化する
    """
    # human の場合はコンソールに出力。ansiの場合は StringIO を返す
    outfile = StringIO() if mode == 'ansi' else sys.stdout
    outfile.write('\n'.join(' '.join(str(elem) for elem in row) for row in self.table) + '\n' + 'total:' + str(self.total) + '\n' + 'damage:' + str(self.damage) + '\n' + 'lesson:' + str(len(self.lesson)) + '\n')
    return outfile