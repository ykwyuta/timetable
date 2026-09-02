import { useState } from 'react'
import type { Meta, SchoolSummary } from '../types'

interface Props {
  meta: Meta
  schools: SchoolSummary[]
  onCreate: (payload: {
    name: string
    school_type: string
    classes_per_grade: number
    include_special_needs: boolean
  }) => Promise<void>
  busy: boolean
}

/**
 * 学校の作成。校種と1学年あたりの学級数だけを指定すれば、教科・教員・講座・
 * 特別教室は標準授業時数から自動生成される（仮定 A-20）。
 */
export function SetupPanel({ meta, schools, onCreate, busy }: Props) {
  const [name, setName] = useState('サンプル中学校')
  const [schoolType, setSchoolType] = useState('junior')
  const [classesPerGrade, setClassesPerGrade] = useState(2)
  const [special, setSpecial] = useState(false)

  const selected = meta.school_types.find((s) => s.value === schoolType)!
  const gradeCount = selected.grades.length
  const totalClasses = classesPerGrade * gradeCount + (special ? 1 : 0)
  const overLimit = totalClasses > meta.max_classes

  return (
    <div className="panel" data-testid="setup-panel">
      <h2>学校を作る</h2>
      <p className="muted" style={{ marginTop: 0, fontSize: 12 }}>
        校種と学級数を選ぶと、学習指導要領の標準授業時数から教科・週コマ数・教員・
        特別教室を自動生成します。生成後に画面から調整できます。
      </p>

      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div className="field" style={{ flex: '1 1 180px' }}>
          <label htmlFor="school-name">学校名</label>
          <input
            id="school-name"
            data-testid="input-school-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="school-type">校種</label>
          <select
            id="school-type"
            data-testid="select-school-type"
            value={schoolType}
            onChange={(e) => setSchoolType(e.target.value)}
          >
            {meta.school_types.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="classes-per-grade">1学年あたりの学級数</label>
          <input
            id="classes-per-grade"
            data-testid="input-classes-per-grade"
            type="number"
            min={1}
            max={12}
            style={{ width: 80 }}
            value={classesPerGrade}
            onChange={(e) => setClassesPerGrade(Number(e.target.value))}
          />
        </div>
        <label className="row" style={{ gap: 4, paddingBottom: 6 }}>
          <input
            type="checkbox"
            data-testid="input-special-needs"
            checked={special}
            onChange={(e) => setSpecial(e.target.checked)}
          />
          特別支援学級を置く
        </label>
        <button
          className="primary"
          data-testid="btn-create-school"
          disabled={busy || overLimit || name.trim() === ''}
          onClick={() =>
            onCreate({
              name,
              school_type: schoolType,
              classes_per_grade: classesPerGrade,
              include_special_needs: special,
            })
          }
        >
          作成する
        </button>
      </div>

      <p className="muted" style={{ fontSize: 12 }} data-testid="setup-summary">
        {selected.label} / 全{totalClasses}学級 / 1コマ{selected.period_minutes}分 / 1日
        {selected.periods_per_day}コマ
        {overLimit && `（上限${meta.max_classes}学級を超えています）`}
      </p>

      <h3>この校種の週コマ数</h3>
      <div className="stats">
        {selected.grades.map((g) => (
          <div key={g.grade} className="stat">
            <b>{g.total}</b> <span className="muted">{g.grade}年</span>
          </div>
        ))}
      </div>

      {schools.length > 0 && (
        <>
          <h3>作成済みの学校</h3>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
            {schools.map((s) => (
              <li key={s.id}>
                {s.name}（{s.school_type_label} / {s.class_count}学級 / 講座{s.course_count}）
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
