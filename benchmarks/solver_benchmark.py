# -*- coding: utf-8 -*-
"""日本の小・中・高の実態に即した時間割インスタンスで整数計画の求解時間を実測する。

docs/requirements.md の性能要件（2.1節）の根拠。週コマ数・学級数・教員あたりの
担当クラス数は、文部科学省の標準授業時数・学校基本調査・教員勤務実態調査に基づく。

    pip install pulp && python3 benchmarks/solver_benchmark.py
"""
import pulp, time

def solve(name, classes, slots_per_day, days, demand, teacher_of, parallel_groups=None, timeout=120):
    """demand: {(clazz, subject): 週コマ数}, teacher_of: {(clazz, subject): teacher}"""
    slots = [(d, l) for d in range(days) for l in range(slots_per_day)]
    p = pulp.LpProblem(name, pulp.LpMinimize)
    x = {(c, s, d, l): pulp.LpVariable(f"x_{c}_{s}_{d}_{l}", 0, 1, pulp.LpBinary)
         for (c, s) in demand for (d, l) in slots}
    slack = []
    # 各クラス・各コマは高々1科目
    for c in classes:
        subs = [s for (cc, s) in demand if cc == c]
        for (d, l) in slots:
            p += pulp.lpSum(x[(c, s, d, l)] for s in subs) <= 1
    # 週コマ数（ソフト制約: 不足分にペナルティ）
    for (c, s), n in demand.items():
        u = pulp.LpVariable(f"u_{c}_{s}", 0, n); slack.append(u)
        p += pulp.lpSum(x[(c, s, d, l)] for (d, l) in slots) + u >= n
    # 1日に同じ科目は1回まで（週4コマ以上の科目は2回まで許容）
    for (c, s), n in demand.items():
        cap = 2 if n > 5 else 1
        for d in range(days):
            p += pulp.lpSum(x[(c, s, d, l)] for l in range(slots_per_day)) <= cap
    # 教員の同時刻重複禁止
    byteacher = {}
    for k, t in teacher_of.items():
        byteacher.setdefault(t, []).append(k)
    for t, ks in byteacher.items():
        for (d, l) in slots:
            p += pulp.lpSum(x[(c, s, d, l)] for (c, s) in ks) <= 1
    # 選択科目の同時展開（高校）: 群内の科目は学年内で同じコマに揃える
    for gi, (grade_classes, subs) in enumerate(parallel_groups or []):
        for (d, l) in slots:
            z = pulp.LpVariable(f"z_{gi}_{d}_{l}", 0, 1, pulp.LpBinary)
            for c in grade_classes:
                for s in subs:
                    if (c, s) in demand:
                        p += x[(c, s, d, l)] <= z
    p += pulp.lpSum(slack)
    t0 = time.time()
    st = p.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=timeout))
    el = time.time() - t0
    unmet = sum(v.value() or 0 for v in slack)
    print(f"{name:28s} 学級{len(classes):3d} 変数{len(p.variables()):7d} 制約{len(p.constraints):6d} "
          f"{pulp.LpStatus[st]:10s} {el:6.2f}s 未充足{unmet:5.0f}コマ")
    return el

# ---- 小学校: 18学級(適正規模上限), 週29コマ, 学級担任制+専科(外国語/理科/算数/体育) ----
ES = {'国語':5,'社会':3,'算数':5,'理科':3,'音楽':1,'図画工作':1,'家庭':2,'体育':3,
      '道徳':1,'特別活動':1,'総合':2,'外国語':2}   # 5・6年相当 計29
def elementary(n_classes):
    classes=[f'{i//3+1}-{i%3+1}' for i in range(n_classes)]
    demand={}; tea={}
    senka={'外国語':4,'理科':4,'算数':6,'体育':6}   # 専科教員1人あたり担当クラス数
    for i,c in enumerate(classes):
        for s,n in ES.items():
            demand[(c,s)]=n
            tea[(c,s)] = f'専科{s}_{i//senka[s]}' if s in senka else f'担任{c}'
    return classes, demand, tea

# ---- 中学校: 週29コマ, 9教科, 教科担任制 ----
JH = {'国語':4,'社会':3,'数学':4,'理科':4,'音楽':1,'美術':1,'保健体育':3,'技術・家庭':2,
      '外国語':4,'道徳':1,'総合':1,'特別活動':1}   # 計29
def junior(n_classes):
    classes=[f'{i//(n_classes//3)+1}-{i%(n_classes//3)+1}' for i in range(n_classes)]
    demand={}; tea={}
    per={'国語':4,'社会':5,'数学':4,'理科':4,'音楽':8,'美術':8,'保健体育':6,'技術・家庭':8,'外国語':4}
    for i,c in enumerate(classes):
        for s,n in JH.items():
            demand[(c,s)]=n
            tea[(c,s)] = f'担任{c}' if s in ('道徳','総合','特別活動') else f'{s}_T{i//per[s]}'
    return classes, demand, tea

# ---- 高校: 週30単位時間, 必履修中心 + 選択科目の同時展開 ----
HS = {'国語':4,'地理歴史':3,'公民':2,'数学':5,'理科':4,'保健体育':3,'芸術':2,
      '外国語':5,'情報':1,'総合的な探究':1}   # 計30
def high(n_classes):
    per_grade=n_classes//3
    classes=[f'{i//per_grade+1}年{i%per_grade+1}組' for i in range(n_classes)]
    demand={}; tea={}
    per={'国語':4,'地理歴史':5,'公民':8,'数学':3,'理科':3,'保健体育':6,'芸術':8,'外国語':3,'情報':8,'総合的な探究':8}
    for i,c in enumerate(classes):
        for s,n in HS.items():
            demand[(c,s)]=n; tea[(c,s)]=f'{s}_T{i//per[s]}'
    # 2・3年の 地歴/理科/芸術 を選択科目群として同時展開
    groups=[]
    for g in (2,3):
        gc=[c for c in classes if c.startswith(f'{g}年')]
        groups.append((gc, ['地理歴史','理科','芸術']))
    return classes, demand, tea, groups

print("=== 実態に基づく規模での求解時間 ===")
for n in (12, 18, 24):
    c,d,t = elementary(n); solve(f"小学校 {n}学級(週29コマ)", c, 6, 5, d, t)
for n in (9, 12, 18):
    c,d,t = junior(n);     solve(f"中学校 {n}学級(週29コマ)", c, 6, 5, d, t)
for n in (15, 24, 30):
    c,d,t,g = high(n);     solve(f"高校 {n}学級(週30コマ,選択展開)", c, 6, 5, d, t, g)

print("\n=== 高校の求解時間のばらつき（選択展開あり／なし） ===")
for n in (15, 18, 21, 24, 27, 30):
    c,d,t,g = high(n)
    solve(f"高校 {n}学級 選択展開あり", c, 6, 5, d, t, g, timeout=180)
for n in (15, 24, 30):
    c,d,t,g = high(n)
    solve(f"高校 {n}学級 選択展開なし", c, 6, 5, d, t, None, timeout=180)
