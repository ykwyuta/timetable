from gym.envs.registration import register

register(
    id='timetable-case0000-v0001',
    entry_point='env.case0000:TimeTable'
)
register(
    id='timetable-case0001-v0001',
    entry_point='env.case0001v0001:TimeTable'
)
register(
    id='timetable-case0001-v0002',
    entry_point='env.case0001v0002:TimeTable'
)