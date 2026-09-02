import type { Timetable, Violation } from '../types'

interface Props {
  timetable: Timetable
  onSelect: (violation: Violation) => void
}

/**
 * 違反一覧。ハード違反（赤）を先に、ソフト違反（黄）を後に並べる。
 * 行をクリックすると、その違反に関係する対象へ表示を切り替える。
 */
export function ViolationPanel({ timetable, onSelect }: Props) {
  const { summary, violations } = timetable
  return (
    <div className="panel">
      <h2>制約チェック</h2>
      <div className="stats" style={{ marginBottom: 10 }}>
        <div className={`stat ${summary.hard_violations === 0 ? 'ok' : 'hard'}`}>
          <b data-testid="hard-count">{summary.hard_violations}</b> <span className="muted">ハード違反</span>
        </div>
        <div className={`stat ${summary.soft_violations === 0 ? 'ok' : 'soft'}`}>
          <b data-testid="soft-count">{summary.soft_violations}</b> <span className="muted">ソフト違反</span>
        </div>
        <div className={`stat ${summary.unmet_periods === 0 ? 'ok' : 'hard'}`}>
          <b data-testid="unmet-count">{summary.unmet_periods}</b> <span className="muted">未配置コマ</span>
        </div>
      </div>

      {violations.length === 0 ? (
        <p className="muted" data-testid="no-violations" style={{ margin: 0 }}>
          違反はありません。
        </p>
      ) : (
        <ul className="violations" data-testid="violation-list">
          {violations.map((v, i) => (
            <li
              key={`${v.code}-${i}`}
              className={v.severity}
              data-testid={`violation-${v.code}`}
              data-severity={v.severity}
              onClick={() => onSelect(v)}
            >
              <span className="code">{v.code}</span>
              {v.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
