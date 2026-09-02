import type {
  AssignmentSnapshot,
  Meta,
  SchoolSummary,
  SolveJob,
  Timetable,
  TimetableRow,
} from './types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // JSON でないレスポンスはそのまま
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  meta: () => request<Meta>('/api/meta'),

  listSchools: () => request<SchoolSummary[]>('/api/schools'),

  createSchool: (payload: {
    name: string
    school_type: string
    classes_per_grade: number
    include_special_needs: boolean
  }) => request<SchoolSummary>('/api/schools', { method: 'POST', body: JSON.stringify(payload) }),

  deleteSchool: (schoolId: number) =>
    request<void>(`/api/schools/${schoolId}`, { method: 'DELETE' }),

  listTimetables: (schoolId: number) =>
    request<TimetableRow[]>(`/api/schools/${schoolId}/timetables`),

  startSolve: (
    schoolId: number,
    payload: { source_timetable_id?: number | null; time_limit_sec?: number; name?: string },
  ) =>
    request<SolveJob>(`/api/schools/${schoolId}/solve`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getJob: (jobId: string) => request<SolveJob>(`/api/jobs/${jobId}`),

  cancelJob: (jobId: string) => request<SolveJob>(`/api/jobs/${jobId}/cancel`, { method: 'POST' }),

  getTimetable: (id: number) => request<Timetable>(`/api/timetables/${id}`),

  addAssignment: (timetableId: number, payload: { course_id: number; day: number; period: number }) =>
    request<Timetable>(`/api/timetables/${timetableId}/assignments`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  moveAssignment: (timetableId: number, assignmentId: number, payload: { day: number; period: number }) =>
    request<Timetable>(`/api/timetables/${timetableId}/assignments/${assignmentId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  deleteAssignment: (timetableId: number, assignmentId: number) =>
    request<Timetable>(`/api/timetables/${timetableId}/assignments/${assignmentId}`, {
      method: 'DELETE',
    }),

  setLock: (timetableId: number, assignmentId: number, locked: boolean) =>
    request<Timetable>(`/api/timetables/${timetableId}/assignments/${assignmentId}/lock`, {
      method: 'POST',
      body: JSON.stringify({ locked }),
    }),

  replaceAssignments: (timetableId: number, assignments: AssignmentSnapshot[]) =>
    request<Timetable>(`/api/timetables/${timetableId}/assignments`, {
      method: 'PUT',
      body: JSON.stringify({ assignments }),
    }),

  exportUrl: (timetableId: number, by: 'class' | 'teacher') =>
    `${BASE}/api/timetables/${timetableId}/export.csv?by=${by}`,
}
