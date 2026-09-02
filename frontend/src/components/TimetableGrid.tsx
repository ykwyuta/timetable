import { useDraggable, useDroppable } from '@dnd-kit/core'
import type { Assignment, Course, Timetable, Violation } from '../types'

export type ViewMode = 'class' | 'teacher'

interface Props {
  timetable: Timetable
  view: ViewMode
  entityId: number
  onToggleLock: (assignment: Assignment) => void
  highlight: { slots: Set<string>; severity: Map<string, 'hard' | 'soft'> }
}

export function slotKey(day: number, period: number): string {
  return `${day}:${period}`
}

/** 違反から「どのコマを光らせるか」を決める。表示中の対象に関係するものだけ拾う。 */
export function computeHighlight(
  timetable: Timetable,
  view: ViewMode,
  entityId: number,
): { slots: Set<string>; severity: Map<string, 'hard' | 'soft'> } {
  const slots = new Set<string>()
  const severity = new Map<string, 'hard' | 'soft'>()
  const courseById = new Map(timetable.courses.map((c) => [c.id, c]))

  const relevant = (v: Violation): boolean => {
    if (view === 'class') {
      if (v.class_ids.includes(entityId)) return true
      return v.course_ids.some((id) => courseById.get(id)?.class_ids.includes(entityId))
    }
    if (v.teacher_ids.includes(entityId)) return true
    return v.course_ids.some((id) => courseById.get(id)?.teacher_id === entityId)
  }

  for (const v of timetable.violations) {
    if (!relevant(v)) continue
    const explicit = v.slots.map((s) => slotKey(s.day, s.period))
    // コマが明示されていない違反（週コマ数の不足など）は、その講座が置かれている
    // コマをすべて光らせる
    const derived =
      explicit.length > 0
        ? explicit
        : timetable.assignments
            .filter((a) => v.course_ids.includes(a.course_id))
            .map((a) => slotKey(a.day, a.period))
    for (const key of derived) {
      slots.add(key)
      if (v.severity === 'hard' || severity.get(key) !== 'hard') {
        severity.set(key, v.severity)
      }
    }
  }
  return { slots, severity }
}

function Chip({
  assignment,
  course,
  view,
  classNames,
  isElective,
  onToggleLock,
}: {
  assignment: Assignment
  course: Course
  view: ViewMode
  classNames: string
  isElective: boolean
  onToggleLock: (a: Assignment) => void
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `assign:${assignment.id}`,
    data: { type: 'assignment', assignment },
    disabled: assignment.locked,
  })

  return (
    <div
      ref={setNodeRef}
      className={[
        'chip',
        course.is_core ? 'core' : 'non-core',
        assignment.locked ? 'locked' : '',
        isElective ? 'elective' : '',
        isDragging ? 'dragging' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      data-testid={`chip-${assignment.id}`}
      data-course-id={course.id}
      data-locked={assignment.locked ? 'true' : 'false'}
      {...listeners}
      {...attributes}
    >
      <div className="chip-title">
        <span>{course.short_name}</span>
        <button
          className="lock-btn"
          title={assignment.locked ? '固定を解除' : 'このコマを固定する'}
          aria-label={assignment.locked ? '固定を解除' : 'このコマを固定する'}
          data-testid={`lock-${assignment.id}`}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation()
            onToggleLock(assignment)
          }}
        >
          {assignment.locked ? '🔒' : '🔓'}
        </button>
      </div>
      <div className="chip-sub">{view === 'class' ? course.teacher_name : classNames}</div>
    </div>
  )
}

function Cell({
  day,
  period,
  children,
  blocked,
  severity,
}: {
  day: number
  period: number
  children: React.ReactNode
  blocked: boolean
  severity: 'hard' | 'soft' | undefined
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `cell:${day}:${period}`,
    data: { type: 'cell', day, period },
  })
  return (
    <td>
      <div
        ref={setNodeRef}
        className={[
          'cell',
          isOver ? 'droppable-over' : '',
          blocked ? 'blocked' : '',
          severity === 'hard' ? 'violation-hard' : severity === 'soft' ? 'violation-soft' : '',
        ]
          .filter(Boolean)
          .join(' ')}
        data-testid={`cell-${day}-${period}`}
        data-violation={severity ?? ''}
      >
        {children}
      </div>
    </td>
  )
}

export function TimetableGrid({ timetable, view, entityId, onToggleLock, highlight }: Props) {
  const { school } = timetable
  const courseById = new Map(timetable.courses.map((c) => [c.id, c]))
  const classById = new Map(timetable.classes.map((c) => [c.id, c]))

  const belongs = (course: Course): boolean =>
    view === 'class' ? course.class_ids.includes(entityId) : course.teacher_id === entityId

  const cells = new Map<string, Assignment[]>()
  for (const a of timetable.assignments) {
    const course = courseById.get(a.course_id)
    if (!course || !belongs(course)) continue
    const key = slotKey(a.day, a.period)
    const list = cells.get(key) ?? []
    list.push(a)
    cells.set(key, list)
  }

  const blockedSet = new Set(
    timetable.blocked_slots
      .filter((b) => b.class_id === null || (view === 'class' && b.class_id === entityId))
      .map((b) => slotKey(b.day, b.period)),
  )
  const teacher = view === 'teacher' ? timetable.teachers.find((t) => t.id === entityId) : undefined
  for (const u of teacher?.unavailable ?? []) blockedSet.add(slotKey(u.day, u.period))

  return (
    <table className="grid" data-testid="timetable-grid">
      <thead>
        <tr>
          <th className="period-head" />
          {school.day_names.map((name, day) => (
            <th key={day}>{name}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: school.periods_per_day }, (_, period) => (
          <tr key={period}>
            <th className="period-head">{period + 1}限</th>
            {Array.from({ length: school.days }, (_, day) => {
              const key = slotKey(day, period)
              return (
                <Cell
                  key={day}
                  day={day}
                  period={period}
                  blocked={blockedSet.has(key)}
                  severity={highlight.severity.get(key)}
                >
                  {(cells.get(key) ?? []).map((a) => {
                    const course = courseById.get(a.course_id)!
                    return (
                      <Chip
                        key={a.id}
                        assignment={a}
                        course={course}
                        view={view}
                        isElective={course.group_id !== null}
                        classNames={course.class_ids
                          .map((id) => classById.get(id)?.name ?? '')
                          .join('・')}
                        onToggleLock={onToggleLock}
                      />
                    )
                  })}
                </Cell>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
