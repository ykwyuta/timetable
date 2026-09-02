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
  1  現代文 週3
  2  古典 週2
  3  漢文 週1
  4  数学 週6 教師A
  5  英語 週6 教師A
  6  日本史 週2
  7  世界史 週2
  8  化学 週2
  9  物理 週2
  10 生物 週2
  11 数学 週6 教師B
  12 英語 週6 教師B
  13 体育 週2
  14 美術 週1
  15 書道 週1
  16 保健 週1
  """
  
  CLASS_LIST = [0, 1, 2, 3, 4, 5]

  CLASS_SIZE = len(CLASS_LIST)
  
  CLASS_LESSON = {
    1 : [0, 1, 2, 3, 4, 5],
    2 : [0, 1, 2, 3, 4, 5],
    3 : [0, 1, 2, 3, 4, 5],
    4 : [0, 1, 2],
    5 : [0, 1, 2],
    6 : [0, 1, 2],
    7 : [3, 4, 5],
    8 : [0, 1, 2, 3],
    9 : [2, 3, 4, 5],
    10: [0, 3, 4, 5],
    11: [3, 4, 5],
    12: [3, 4, 5],
    13 : [0, 1, 2, 3, 4, 5],
    14 : [0, 1, 2, 3, 4, 5],
    15 : [0, 1, 2, 3, 4, 5],
    16 : [0, 1, 2, 3, 4, 5]
  }

  LESSON_NAME = {
    -1: '禁 ', # 1  現代文 週3
    0 : '未 ', # 1  現代文 週3
    1 : '現0', # 1  現代文 週3
    2 : '古0', # 2  古典 週2
    3 : '漢0', # 3  漢文 週1
    4 : '数0', # 4  数学 週6 教師A
    5 : '英0', # 5  英語 週6 教師A
    6 : '日0', # 6  日本史 週2
    7 : '世0', # 7  世界史 週2
    8 : '化0', # 8  化学 週2
    9 : '物0', # 9  物理 週2
    10: '生0', # 10 生物 週2
    11: '数1', # 11 数学 週6 教師B
    12: '英1', # 12 英語 週6 教師B
    13: '体0', # 13 体育 週2
    14: '美0', # 14 美術 週1
    15: '書0', # 15 書道 週1
    16: '保0'  # 16 保健 週1
  }

  CLASS_LESSON_TIMES = {
    1 : 3,
    2 : 2,
    3 : 1,
    4 : 6,
    5 : 6,
    6 : 2,
    7 : 2,
    8 : 2,
    9 : 2,
    10: 2,
    11: 6,
    12: 6,
    13 : 2,
    14 : 1,
    15 : 1,
    16 : 1
  }

  WEEK_SIZE = 6
  
  DAY_SIZE = 5
  
  TIME_TABLE = np.zeros((CLASS_SIZE, WEEK_SIZE * DAY_SIZE))

  LESSON_LIST = CLASS_LESSON.keys()

  LESSON_SIZE = len(LESSON_LIST)

  TOTAL_LESSON = CLASS_SIZE * WEEK_SIZE * DAY_SIZE

  MAX_DAMAGE = 100
  
  def __init__(self):
    super().__init__()
    # 土曜日の授業のコマ数
    for i in range(self.CLASS_SIZE):
      self.TIME_TABLE[i][-1] = -1
      self.TIME_TABLE[i][-2] = -1
    self.action_space = gym.spaces.Discrete(self.CLASS_SIZE * self.WEEK_SIZE * self.DAY_SIZE * self.LESSON_SIZE)
    self.observation_space = gym.spaces.Box(
        low = -1,
        high = max(self.LESSON_LIST),
        shape = self.TIME_TABLE.shape
    )
    # self.reward_range = [0, self.TOTAL_LESSON]
    self.reward_range = [0, 1]
    self.action2lp = []
    for lesson in range(self.LESSON_SIZE):
      for pos in range(self.CLASS_SIZE * self.WEEK_SIZE * self.DAY_SIZE):
        self.action2lp.append((lesson + 1, pos))
    self.reset()

  def reset(self):
    """
    状態を初期化し、初期の観測値を返す
    """
    self.damage = 0
    self.total = 0
    self.progress = 0
    self.table = self.TIME_TABLE.copy()
    self.lesson = list(self.LESSON_LIST)
    return self.table.copy()
    
  def step(self, action):
    """
   1ステップ進める処理を記述。戻り値は observation, reward, done(ゲーム終了したか), info(追加の情報の辞書)
    """
    # 配置する授業を取り出す
    lesson, pos = self.action2lp[action]

    # 授業を配置することが可能化どうか
    if self._is_bookable(pos, lesson):
      table = self.table.copy()
      shape = table.shape
      table = table.reshape(1, shape[0] * shape[1])
      table[0][pos] = lesson
      self.table = table.reshape(shape)
      self.progress += 1
      moved = True
      self.damage = 0
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
    if moved is None:
      return -10
    if moved:
      # 特典の計算。授業が分散されて配置できていると高得点になるようにしたいけど効率的な判定方法分からないので一旦スルー
      # return self.progress
      return 1
    else:
      return 0
  def _get_damage(self, moved):
    if moved or moved is None:
      return 0
    else:
      return 1
  
  def _is_bookable(self, pos, lesson):
    """
    授業を配置することが可能か否かを返す
    """
    table = self.table.copy()
    shape = self.table.shape
    table = table.reshape(1, shape[0] * shape[1])
    # 配置不可の枠には配置できない
    if table[0][pos] == -1:
      return False
    # すでに配置済みのところには配置できない
    if table[0][pos] > 0:
      return False
    # 更新をしてみる
    table[0][pos] = lesson
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
    # 週に指定の回数以上の授業を担当のクラス以外に実施できない
    table = table.reshape(self.CLASS_SIZE, self.WEEK_SIZE * self.DAY_SIZE)
    for i in range(self.CLASS_SIZE):
      row = table[i]
      count = Counter(row)
      # 担当のクラス以外の授業は実施できない
      if len([num for num in count.items() if num[0] > 0 and i not in self.CLASS_LESSON[num[0]]]) > 0:
        return False
      # 週に指定の回数以上の授業を実施できない
      if len([num for num in count.items() if num[0] > 0 and num[1] > self.CLASS_LESSON_TIMES[num[0]]]) > 0:
        return False
    return True 
  def _is_done(self):
    """
    すべての授業を配置するか、授業を配置できない状態がMAX_DAMAGE回続くと終了
    """
    if self.damage >= self.MAX_DAMAGE:
      return True
    elif self.TOTAL_LESSON - self.progress == 0:
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
    outfile.write('\n'.join(' '.join(self.LESSON_NAME[int(elem)] for elem in row) for row in self.table) + '\n' + \
      'total:' + str(self.total) + '\n' + \
      'damage:' + str(self.damage) + '\n' + \
      'lesson:' + str(self.TOTAL_LESSON - self.progress) + '\n')
    return outfile
