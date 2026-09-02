import { expect, type Locator, type Page } from '@playwright/test'

/**
 * dnd-kit の PointerSensor に対するドラッグ&ドロップ。
 *
 * PointerSensor は activationConstraint.distance を持つため、押下したあと
 * 一定距離動かさないとドラッグが始まらない。マウス移動を複数ステップに分け、
 * 開始直後に小さく動かしてドラッグを確実に発火させている。
 */
export async function dragTo(page: Page, source: Locator, target: Locator): Promise<void> {
  await source.scrollIntoViewIfNeeded()
  const from = await source.boundingBox()
  if (!from) throw new Error('ドラッグ元の位置を取得できません')
  await target.scrollIntoViewIfNeeded()
  const to = await target.boundingBox()
  if (!to) throw new Error('ドロップ先の位置を取得できません')

  const start = { x: from.x + from.width / 2, y: from.y + from.height / 2 }
  const end = { x: to.x + to.width / 2, y: to.y + to.height / 2 }

  await page.mouse.move(start.x, start.y)
  await page.mouse.down()
  // 活性化距離（4px）を超えるための最初の一歩
  await page.mouse.move(start.x + 8, start.y + 8, { steps: 4 })
  await page.mouse.move(end.x, end.y, { steps: 12 })
  await page.mouse.move(end.x, end.y)
  await page.mouse.up()
}

export interface SchoolOptions {
  name: string
  type: '小学校' | '中学校' | '高等学校'
  classesPerGrade: number
  specialNeeds?: boolean
}

/**
 * 学校を作成する。作成後はセットアップ画面のまま（まだ時間割はない）。
 *
 * 既に時間割が表示されている場合（前のテストで作った学校が自動選択されている等）は、
 * 先に「新しい学校を作る」を押してセットアップ画面へ戻す。読み込み中に画面が
 * 入れ替わると入力が失われるため、表示が落ち着くまで待ってから操作する。
 */
export async function createSchool(page: Page, options: SchoolOptions): Promise<void> {
  await expect(page.getByTestId('school-loading')).toHaveCount(0)
  await expect(
    page.getByTestId('setup-panel').or(page.getByTestId('btn-new-school')),
  ).toBeVisible()
  if ((await page.getByTestId('setup-panel').count()) === 0) {
    await page.getByTestId('btn-new-school').click()
  }
  await expect(page.getByTestId('setup-panel')).toBeVisible()
  await page.getByTestId('input-school-name').fill(options.name)
  await page.getByTestId('select-school-type').selectOption({ label: options.type })
  await page.getByTestId('input-classes-per-grade').fill(String(options.classesPerGrade))
  if (options.specialNeeds) {
    await page.getByTestId('input-special-needs').check()
  }
  await page.getByTestId('btn-create-school').click()
  await expect(page.getByTestId('notice-banner')).toContainText(options.name)
}

/** 自動提案を実行し、時間割が表示されるまで待つ。 */
export async function solve(page: Page, testId: 'btn-solve' | 'btn-resolve' = 'btn-solve'): Promise<void> {
  await page.getByTestId(testId).click()
  await expect(page.getByTestId('notice-banner')).toContainText('提案しました', { timeout: 90_000 })
  await expect(page.getByTestId('timetable-grid')).toBeVisible()
}

/** 表示中のグリッドにある最初のコマ（チップ）を返す。 */
export function firstChip(page: Page): Locator {
  return page.getByTestId('timetable-grid').locator('.chip').first()
}

/** グリッド上のチップの割当IDを返す。 */
export async function assignmentIdOf(chip: Locator): Promise<string> {
  const testId = await chip.getAttribute('data-testid')
  if (!testId) throw new Error('チップの data-testid がありません')
  return testId.replace('chip-', '')
}

/** 指定した学級の時間割で、空いているコマを1つ探す。 */
export async function findEmptyCell(page: Page): Promise<Locator> {
  const grid = page.getByTestId('timetable-grid')
  const cells = grid.locator('[data-testid^="cell-"]')
  const count = await cells.count()
  for (let i = 0; i < count; i++) {
    const cell = cells.nth(i)
    if ((await cell.locator('.chip').count()) === 0) return cell
  }
  throw new Error('空いているコマが見つかりません')
}

/** 指定した学級の時間割で、チップが入っているコマを2つ探す（同一学級・別コマ）。 */
export async function findTwoOccupiedCells(page: Page): Promise<[Locator, Locator]> {
  const grid = page.getByTestId('timetable-grid')
  const cells = grid.locator('[data-testid^="cell-"]')
  const count = await cells.count()
  const occupied: Locator[] = []
  for (let i = 0; i < count && occupied.length < 2; i++) {
    const cell = cells.nth(i)
    if ((await cell.locator('.chip').count()) === 1) occupied.push(cell)
  }
  if (occupied.length < 2) throw new Error('埋まっているコマが2つ見つかりません')
  return [occupied[0], occupied[1]]
}
