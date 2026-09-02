export type Severity = 'hard' | 'soft'

export interface Slot {
  day: number
  period: number
}

export interface School {
  id: number
  name: string
  school_type: string
  school_type_label: string
  days: number
  periods_per_day: number
  period_minutes: number
  day_names: string[]
}

export interface SchoolSummary extends School {
  class_count: number
  course_count: number
  timetable_count: number
}

export interface SchoolClass {
  id: number
  name: string
  grade: number
  kind: 'normal' | 'special_needs'
}

export interface Teacher {
  id: number
  name: string
  kind: string
  max_weekly_periods: number
  unavailable: Slot[]
}

export interface Course {
  id: number
  subject_id: number
  subject_name: string
  short_name: string
  is_core: boolean
  room_type: string | null
  teacher_id: number
  teacher_name: string
  class_ids: number[]
  weekly_periods: number
  max_per_day: number
  prefers_double: boolean
  group_id: number | null
  placed: number
}

export interface Assignment {
  id: number
  course_id: number
  day: number
  period: number
  locked: boolean
}

export interface Violation {
  code: string
  severity: Severity
  message: string
  course_ids: number[]
  class_ids: number[]
  teacher_ids: number[]
  slots: Slot[]
}

export interface Summary {
  total_periods: number
  placed_periods: number
  unmet_periods: number
  hard_violations: number
  soft_violations: number
  locked: number
}

export interface ParallelGroup {
  id: number
  name: string
  course_ids: number[]
}

export interface Timetable {
  id: number
  name: string
  parent_id: number | null
  created_at: string
  school: School
  classes: SchoolClass[]
  teachers: Teacher[]
  courses: Course[]
  parallel_groups: ParallelGroup[]
  blocked_slots: (Slot & { class_id: number | null; reason: string })[]
  assignments: Assignment[]
  violations: Violation[]
  unplaced: { course_id: number; remaining: number }[]
  summary: Summary
}

export interface TimetableRow {
  id: number
  name: string
  parent_id: number | null
  created_at: string
  assignment_count: number
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface SolveJob {
  id: string
  school_id: number
  status: JobStatus
  elapsed_sec: number
  timetable_id: number | null
  error: string | null
  violations: Violation[]
  unmet_periods: number | null
  total_periods: number | null
  solver_status: string | null
  timed_out: boolean
  stats: Record<string, number>
}

export interface Meta {
  school_types: {
    value: string
    label: string
    period_minutes: number
    periods_per_day: number
    grades: {
      grade: number
      weekly: Record<string, number>
      electives: { name: string; periods: number; subjects: string[] }[]
      total: number
    }[]
  }[]
  constraints: { code: string; label: string; severity: Severity; weight: number }[]
  max_classes: number
  day_names: string[]
}

/** undo/redo のスナップショット。API の一括置換に渡せる形で持つ。 */
export interface AssignmentSnapshot {
  course_id: number
  day: number
  period: number
  locked: boolean
}
