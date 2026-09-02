import { useDraggable, useDroppable } from '@dnd-kit/core'
import type { Course, Timetable } from '../types'
import type { ViewMode } from './TimetableGrid'

interface Props {
  timetable: Timetable
  view: ViewMode
  entityId: number
}

function UnplacedChip({ course, remaining }: { course: Course; remaining: number }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `course:${course.id}`,
    data: { type: 'course', courseId: course.id },
  })
  return (
    <div
      ref={setNodeRef}
      className={['chip', course.is_core ? 'core' : 'non-core', isDragging ? 'dragging' : '']
        .filter(Boolean)
        .join(' ')}
      data-testid={`unplaced-${course.id}`}
      {...listeners}
      {...attributes}
    >
      <div className="chip-title">
        {course.short_name} <span className="muted">残{remaining}</span>
      </div>
      <div className="chip-sub">{course.teacher_name}</div>
    </div>
  )
}

/**
 * 未配置の講座置き場。ここからコマへドラッグして配置し、コマからここへ戻すと外れる。
 */
export function UnplacedTray({ timetable, view, entityId }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: 'tray', data: { type: 'tray' } })
  const courseById = new Map(timetable.courses.map((c) => [c.id, c]))

  const items = timetable.unplaced
    .map((u) => ({ course: courseById.get(u.course_id)!, remaining: u.remaining }))
    .filter(({ course }) =>
      view === 'class' ? course.class_ids.includes(entityId) : course.teacher_id === entityId,
    )

  return (
    <div className="panel">
      <h2>未配置のコマ</h2>
      <div
        ref={setNodeRef}
        className={`tray ${isOver ? 'droppable-over' : ''}`}
        data-testid="unplaced-tray"
      >
        {items.length === 0 ? (
          <div className="tray-empty" data-testid="tray-empty">
            表示中の対象に未配置のコマはありません
          </div>
        ) : (
          items.map(({ course, remaining }) => (
            <UnplacedChip key={course.id} course={course} remaining={remaining} />
          ))
        )}
      </div>
      <p className="muted" style={{ fontSize: 12, margin: '8px 0 0' }}>
        コマをここへドラッグすると配置を外せます。
      </p>
    </div>
  )
}
