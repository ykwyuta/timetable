import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DndContext, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import type { DragEndEvent } from '@dnd-kit/core'
import { api, ApiError } from './api'
import { SetupPanel } from './components/SetupPanel'
import { TimetableGrid, computeHighlight } from './components/TimetableGrid'
import type { ViewMode } from './components/TimetableGrid'
import { UnplacedTray } from './components/UnplacedTray'
import { ViolationPanel } from './components/ViolationPanel'
import type {
  Assignment,
  AssignmentSnapshot,
  Meta,
  SchoolSummary,
  SolveJob,
  Timetable,
  TimetableRow,
  Violation,
} from './types'

// 仮定 A-30: 求解ジョブのポーリング間隔。要件では2秒としていたが、小・中規模校は
// 数秒で解けるため、体感とE2Eの所要時間を優先して1秒にした。
const POLL_INTERVAL_MS = 1000

function snapshotOf(timetable: Timetable): AssignmentSnapshot[] {
  return timetable.assignments.map((a) => ({
    course_id: a.course_id,
    day: a.day,
    period: a.period,
    locked: a.locked,
  }))
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [schools, setSchools] = useState<SchoolSummary[]>([])
  const [schoolId, setSchoolId] = useState<number | null>(null)
  const [versions, setVersions] = useState<TimetableRow[]>([])
  const [timetable, setTimetable] = useState<Timetable | null>(null)
  const [view, setView] = useState<ViewMode>('class')
  const [entityId, setEntityId] = useState<number | null>(null)
  const [job, setJob] = useState<SolveJob | null>(null)
  const [busy, setBusy] = useState(false)
  // 学校を選んでから、その時間割が届くまでの間。ここで「学校を作る」画面を
  // 出してしまうと、読み込み完了時に画面が入れ替わって操作が失われる
  const [schoolLoading, setSchoolLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [past, setPast] = useState<AssignmentSnapshot[][]>([])
  const [future, setFuture] = useState<AssignmentSnapshot[][]>([])
  const pollTimer = useRef<number | null>(null)

  // ---- 初期ロード ----
  useEffect(() => {
    void (async () => {
      try {
        const [m, s] = await Promise.all([api.meta(), api.listSchools()])
        setMeta(m)
        setSchools(s)
        if (s.length > 0) {
          setSchoolLoading(true)
          setSchoolId(s[0].id)
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    })()
  }, [])

  const loadVersions = useCallback(async (id: number) => {
    const rows = await api.listTimetables(id)
    setVersions(rows)
    return rows
  }, [])

  useEffect(() => {
    if (schoolId === null) {
      setSchoolLoading(false)
      return
    }
    void (async () => {
      try {
        const rows = await loadVersions(schoolId)
        if (rows.length > 0) {
          const tt = await api.getTimetable(rows[0].id)
          applyTimetable(tt, true)
        } else {
          setTimetable(null)
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setSchoolLoading(false)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schoolId])

  const applyTimetable = (tt: Timetable, resetHistory = false) => {
    setTimetable(tt)
    if (resetHistory) {
      setPast([])
      setFuture([])
    }
    setEntityId((current) => {
      const ids =
        view === 'class' ? tt.classes.map((c) => c.id) : tt.teachers.map((t) => t.id)
      return current !== null && ids.includes(current) ? current : (ids[0] ?? null)
    })
  }

  // 表示対象（クラス／教員）が変わったら、そのビューの先頭を選び直す
  useEffect(() => {
    if (!timetable) return
    const ids = view === 'class' ? timetable.classes.map((c) => c.id) : timetable.teachers.map((t) => t.id)
    setEntityId((current) => (current !== null && ids.includes(current) ? current : (ids[0] ?? null)))
  }, [view, timetable])

  // ---- 編集操作（undo 用にスナップショットを積んでから実行する） ----
  const mutate = useCallback(
    async (action: (tt: Timetable) => Promise<Timetable>) => {
      if (!timetable) return
      const before = snapshotOf(timetable)
      setError(null)
      try {
        const next = await action(timetable)
        setPast((p) => [...p, before])
        setFuture([])
        applyTimetable(next)
      } catch (e) {
        setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e))
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [timetable, view],
  )

  const undo = async () => {
    if (!timetable || past.length === 0) return
    const target = past[past.length - 1]
    const current = snapshotOf(timetable)
    const next = await api.replaceAssignments(timetable.id, target)
    setPast((p) => p.slice(0, -1))
    setFuture((f) => [current, ...f])
    applyTimetable(next)
  }

  const redo = async () => {
    if (!timetable || future.length === 0) return
    const target = future[0]
    const current = snapshotOf(timetable)
    const next = await api.replaceAssignments(timetable.id, target)
    setFuture((f) => f.slice(1))
    setPast((p) => [...p, current])
    applyTimetable(next)
  }

  // ---- 求解ジョブ ----
  const stopPolling = () => {
    if (pollTimer.current !== null) {
      window.clearInterval(pollTimer.current)
      pollTimer.current = null
    }
  }
  useEffect(() => stopPolling, [])

  const startSolve = async (keepLocks: boolean) => {
    if (schoolId === null) return
    setError(null)
    setNotice(null)
    setBusy(true)
    try {
      const started = await api.startSolve(schoolId, {
        source_timetable_id: keepLocks && timetable ? timetable.id : null,
      })
      setJob(started)
      stopPolling()
      pollTimer.current = window.setInterval(async () => {
        try {
          const current = await api.getJob(started.id)
          setJob(current)
          if (current.status === 'succeeded' && current.timetable_id !== null) {
            stopPolling()
            setBusy(false)
            const tt = await api.getTimetable(current.timetable_id)
            applyTimetable(tt, true)
            await loadVersions(schoolId)
            setNotice(
              `提案しました（${current.elapsed_sec.toFixed(1)}秒 / 未配置${current.unmet_periods ?? 0}コマ` +
                `${current.timed_out ? ' / 時間制限に達したため暫定解' : ''}）`,
            )
          } else if (current.status === 'failed') {
            stopPolling()
            setBusy(false)
            setError(current.error ?? '求解に失敗しました')
          } else if (current.status === 'cancelled') {
            stopPolling()
            setBusy(false)
            setNotice('求解をキャンセルしました')
          }
        } catch (e) {
          stopPolling()
          setBusy(false)
          setError(e instanceof Error ? e.message : String(e))
        }
      }, POLL_INTERVAL_MS)
    } catch (e) {
      setBusy(false)
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const cancelSolve = async () => {
    if (!job) return
    await api.cancelJob(job.id)
  }

  const createSchool = async (payload: {
    name: string
    school_type: string
    classes_per_grade: number
    include_special_needs: boolean
  }) => {
    setBusy(true)
    setError(null)
    try {
      const created = await api.createSchool(payload)
      setSchools(await api.listSchools())
      setSchoolLoading(true)
      setSchoolId(created.id)
      setTimetable(null)
      setNotice(`${created.name} を作成しました（${created.class_count}学級 / 講座${created.course_count}）`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  // ---- ドラッグ&ドロップ ----
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || !timetable) return
    const from = active.data.current as
      | { type: 'assignment'; assignment: Assignment }
      | { type: 'course'; courseId: number }
      | undefined
    const to = over.data.current as
      | { type: 'cell'; day: number; period: number }
      | { type: 'tray' }
      | undefined
    if (!from || !to) return

    if (from.type === 'assignment' && to.type === 'cell') {
      if (from.assignment.day === to.day && from.assignment.period === to.period) return
      void mutate((tt) =>
        api.moveAssignment(tt.id, from.assignment.id, { day: to.day, period: to.period }),
      )
    } else if (from.type === 'assignment' && to.type === 'tray') {
      void mutate((tt) => api.deleteAssignment(tt.id, from.assignment.id))
    } else if (from.type === 'course' && to.type === 'cell') {
      void mutate((tt) =>
        api.addAssignment(tt.id, { course_id: from.courseId, day: to.day, period: to.period }),
      )
    }
  }

  const toggleLock = (assignment: Assignment) => {
    void mutate((tt) => api.setLock(tt.id, assignment.id, !assignment.locked))
  }

  const focusViolation = (v: Violation) => {
    if (!timetable) return
    const courseById = new Map(timetable.courses.map((c) => [c.id, c]))
    if (v.class_ids.length > 0) {
      setView('class')
      setEntityId(v.class_ids[0])
      return
    }
    if (v.teacher_ids.length > 0) {
      setView('teacher')
      setEntityId(v.teacher_ids[0])
      return
    }
    const course = v.course_ids.map((id) => courseById.get(id)).find(Boolean)
    if (course) {
      setView('class')
      setEntityId(course.class_ids[0])
    }
  }

  const highlight = useMemo(
    () =>
      timetable && entityId !== null
        ? computeHighlight(timetable, view, entityId)
        : { slots: new Set<string>(), severity: new Map<string, 'hard' | 'soft'>() },
    [timetable, view, entityId],
  )

  const entities = useMemo(() => {
    if (!timetable) return []
    return view === 'class'
      ? timetable.classes.map((c) => ({ id: c.id, label: c.name }))
      : timetable.teachers.map((t) => ({ id: t.id, label: t.name }))
  }, [timetable, view])

  if (!meta) {
    return (
      <div className="empty-state" data-testid="loading">
        読み込み中…
      </div>
    )
  }

  return (
    <div className="app">
      <header className="appbar">
        <h1>時間割自動編成</h1>
        <div className="field">
          <label htmlFor="school-select">学校</label>
          <select
            id="school-select"
            data-testid="select-school"
            value={schoolId ?? ''}
            onChange={(e) => {
              const next = e.target.value === '' ? null : Number(e.target.value)
              setSchoolLoading(next !== null)
              setTimetable(null)
              setSchoolId(next)
            }}
          >
            <option value="">（未選択）</option>
            {schools.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}（{s.school_type_label}）
              </option>
            ))}
          </select>
        </div>
        {versions.length > 0 && (
          <div className="field">
            <label htmlFor="version-select">版</label>
            <select
              id="version-select"
              data-testid="select-version"
              value={timetable?.id ?? ''}
              onChange={async (e) => {
                const tt = await api.getTimetable(Number(e.target.value))
                applyTimetable(tt, true)
              }}
            >
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="spacer" />
        {busy && job && (
          <div className="progress" data-testid="solve-progress">
            <span className="spinner" />
            <span>
              求解中 {job.elapsed_sec.toFixed(0)}秒
            </span>
            <button data-testid="btn-cancel-solve" onClick={() => void cancelSolve()}>
              キャンセル
            </button>
          </div>
        )}
        <button
          className="primary"
          data-testid="btn-solve"
          disabled={schoolId === null || busy}
          onClick={() => void startSolve(false)}
        >
          自動提案
        </button>
        <button
          data-testid="btn-resolve"
          disabled={schoolId === null || busy || !timetable}
          title="固定したコマを保ったまま、残りを組み直します"
          onClick={() => void startSolve(true)}
        >
          固定を保って再提案
        </button>
      </header>

      <div className="layout">
        <div className="main">
          {error && (
            <div className="banner error" data-testid="error-banner">
              {error}
            </div>
          )}
          {notice && !error && (
            <div className="banner success" data-testid="notice-banner">
              {notice}
            </div>
          )}

          {schoolLoading ? (
            <div className="panel empty-state" data-testid="school-loading">
              時間割を読み込んでいます…
            </div>
          ) : !timetable ? (
            <SetupPanel meta={meta} schools={schools} onCreate={createSchool} busy={busy} />
          ) : (
            <DndContext sensors={sensors} onDragEnd={onDragEnd}>
              <div className="panel">
                <div className="row" style={{ marginBottom: 10 }}>
                  <div className="tabs" style={{ margin: 0 }}>
                    <button
                      className={view === 'class' ? 'active' : ''}
                      data-testid="btn-view-class"
                      onClick={() => setView('class')}
                    >
                      クラス別
                    </button>
                    <button
                      className={view === 'teacher' ? 'active' : ''}
                      data-testid="btn-view-teacher"
                      onClick={() => setView('teacher')}
                    >
                      教員別
                    </button>
                  </div>
                  <select
                    data-testid="select-entity"
                    value={entityId ?? ''}
                    onChange={(e) => setEntityId(Number(e.target.value))}
                  >
                    {entities.map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.label}
                      </option>
                    ))}
                  </select>
                  <div className="spacer" />
                  <button data-testid="btn-undo" disabled={past.length === 0} onClick={() => void undo()}>
                    元に戻す（{past.length}）
                  </button>
                  <button data-testid="btn-redo" disabled={future.length === 0} onClick={() => void redo()}>
                    やり直す（{future.length}）
                  </button>
                </div>

                <div className="stats" style={{ marginBottom: 10 }}>
                  <div className="stat">
                    <b data-testid="placed-count">{timetable.summary.placed_periods}</b>
                    <span className="muted"> / {timetable.summary.total_periods} コマ配置</span>
                  </div>
                  <div className="stat">
                    <b data-testid="locked-count">{timetable.summary.locked}</b>
                    <span className="muted"> コマ固定</span>
                  </div>
                </div>

                {entityId !== null && (
                  <TimetableGrid
                    timetable={timetable}
                    view={view}
                    entityId={entityId}
                    onToggleLock={toggleLock}
                    highlight={highlight}
                  />
                )}
              </div>

              <div style={{ height: 12 }} />
              {entityId !== null && (
                <UnplacedTray timetable={timetable} view={view} entityId={entityId} />
              )}
            </DndContext>
          )}
        </div>

        <div className="side">
          {timetable && <ViolationPanel timetable={timetable} onSelect={focusViolation} />}
          {timetable && (
            <div className="panel">
              <h2>出力</h2>
              <div className="row">
                <a href={api.exportUrl(timetable.id, 'class')} data-testid="link-export-class">
                  クラス別CSV
                </a>
                <a href={api.exportUrl(timetable.id, 'teacher')} data-testid="link-export-teacher">
                  教員別CSV
                </a>
              </div>
            </div>
          )}
          {timetable && (
            <div className="panel">
              <h2>別の学校</h2>
              <button
                data-testid="btn-new-school"
                onClick={() => {
                  setSchoolId(null)
                  setTimetable(null)
                  setVersions([])
                  setNotice(null)
                }}
              >
                新しい学校を作る
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
