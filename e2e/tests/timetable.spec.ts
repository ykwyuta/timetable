import { expect, test } from '@playwright/test'
import {
  assignmentIdOf,
  createSchool,
  dragTo,
  findEmptyCell,
  findTwoOccupiedCells,
  firstChip,
  solve,
} from './helpers'

test.describe('時間割の自動提案と微調整', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: '時間割自動編成' })).toBeVisible()
  })

  test('学校を作って自動提案すると、ハード違反なしで全コマが埋まる', async ({ page }) => {
    await createSchool(page, { name: 'E2E中学校', type: '中学校', classesPerGrade: 1 })
    await solve(page)

    await expect(page.getByTestId('hard-count')).toHaveText('0')
    await expect(page.getByTestId('unmet-count')).toHaveText('0')

    const placed = await page.getByTestId('placed-count').textContent()
    expect(Number(placed)).toBeGreaterThan(0)

    // クラス別ビューに、その学級の週コマ数ぶんのチップが並ぶ
    const chips = page.getByTestId('timetable-grid').locator('.chip')
    await expect.poll(async () => chips.count()).toBeGreaterThanOrEqual(25)
  })

  test('コマをドラッグして重ねると違反が出て、元に戻すと消える', async ({ page }) => {
    await createSchool(page, { name: 'E2E中学校2', type: '中学校', classesPerGrade: 1 })
    await solve(page)
    await expect(page.getByTestId('hard-count')).toHaveText('0')

    const [source, target] = await findTwoOccupiedCells(page)
    await dragTo(page, source.locator('.chip'), target)

    // 同じ学級の同じコマに2つ入るので H1 違反になる
    await expect(page.getByTestId('hard-count')).not.toHaveText('0')
    await expect(page.getByTestId('violation-H1').first()).toContainText('重複しています')
    await expect(target.locator('.chip')).toHaveCount(2)
    await expect(target).toHaveAttribute('data-violation', 'hard')

    // 元に戻す
    await page.getByTestId('btn-undo').click()
    await expect(page.getByTestId('hard-count')).toHaveText('0')
    await expect(target.locator('.chip')).toHaveCount(1)

    // やり直す
    await page.getByTestId('btn-redo').click()
    await expect(page.getByTestId('hard-count')).not.toHaveText('0')

    // もう一度戻して綺麗な状態に
    await page.getByTestId('btn-undo').click()
    await expect(page.getByTestId('hard-count')).toHaveText('0')
  })

  test('コマを未配置トレイへ外し、別のコマへ戻せる', async ({ page }) => {
    await createSchool(page, { name: 'E2E中学校3', type: '中学校', classesPerGrade: 1 })
    await solve(page)
    await expect(page.getByTestId('tray-empty')).toBeVisible()

    const chip = firstChip(page)
    const courseId = await chip.getAttribute('data-course-id')
    await dragTo(page, chip, page.getByTestId('unplaced-tray'))

    // トレイに未配置として現れ、未配置コマ数が1になる
    const unplaced = page.getByTestId(`unplaced-${courseId}`)
    await expect(unplaced).toBeVisible()
    await expect(page.getByTestId('unmet-count')).toHaveText('1')

    // 空いているコマへ戻す
    const empty = await findEmptyCell(page)
    await dragTo(page, unplaced, empty)
    await expect(page.getByTestId('unmet-count')).toHaveText('0')
    await expect(page.getByTestId('tray-empty')).toBeVisible()
    await expect(page.getByTestId('hard-count')).toHaveText('0')
  })

  test('固定したコマは再提案しても動かない', async ({ page }) => {
    await createSchool(page, { name: 'E2E中学校4', type: '中学校', classesPerGrade: 2 })
    await solve(page)

    // 先頭の3コマを固定する
    const grid = page.getByTestId('timetable-grid')
    const lockedCells: { day: string; period: string; course: string }[] = []
    for (let i = 0; i < 3; i++) {
      const chip = grid.locator('.chip[data-locked="false"]').first()
      const id = await assignmentIdOf(chip)
      const course = await chip.getAttribute('data-course-id')
      const cell = chip.locator('xpath=ancestor::div[starts-with(@data-testid,"cell-")]')
      const cellId = (await cell.getAttribute('data-testid'))!.split('-')
      lockedCells.push({ day: cellId[1], period: cellId[2], course: course! })
      await page.getByTestId(`lock-${id}`).click()
      await expect(page.getByTestId('locked-count')).toHaveText(String(i + 1))
    }

    const versionsBefore = await page.getByTestId('select-version').locator('option').count()

    await solve(page, 'btn-resolve')

    // 新しい版ができ、固定は引き継がれている
    await expect(page.getByTestId('select-version').locator('option')).toHaveCount(
      versionsBefore + 1,
    )
    await expect(page.getByTestId('locked-count')).toHaveText('3')
    await expect(page.getByTestId('hard-count')).toHaveText('0')

    // 固定したコマが同じ位置に残っている
    for (const locked of lockedCells) {
      const cell = page.getByTestId(`cell-${locked.day}-${locked.period}`)
      await expect(cell.locator(`.chip[data-course-id="${locked.course}"]`)).toHaveCount(1)
    }
  })

  test('固定したコマはドラッグできない', async ({ page }) => {
    await createSchool(page, { name: 'E2E中学校5', type: '中学校', classesPerGrade: 1 })
    await solve(page)

    const [source, target] = await findTwoOccupiedCells(page)
    const chip = source.locator('.chip')
    const id = await assignmentIdOf(chip)
    await page.getByTestId(`lock-${id}`).click()
    await expect(page.getByTestId('locked-count')).toHaveText('1')

    await dragTo(page, chip, target)

    // 動いていない（元のコマに残っている）
    await expect(source.locator(`[data-testid="chip-${id}"]`)).toHaveCount(1)
    await expect(page.getByTestId('hard-count')).toHaveText('0')
  })

  test('クラス別と教員別を切り替えられる', async ({ page }) => {
    await createSchool(page, { name: 'E2E中学校6', type: '中学校', classesPerGrade: 1 })
    await solve(page)

    const classOptions = await page.getByTestId('select-entity').locator('option').allTextContents()
    expect(classOptions).toContain('1年1組')

    await page.getByTestId('btn-view-teacher').click()
    const teacherOptions = await page
      .getByTestId('select-entity')
      .locator('option')
      .allTextContents()
    expect(teacherOptions.length).toBeGreaterThan(0)
    expect(teacherOptions.some((t) => t.includes('教諭') || t.includes('担任'))).toBe(true)

    // 教員別ビューでも、その教員のコマだけが並ぶ
    await expect(page.getByTestId('timetable-grid').locator('.chip').first()).toBeVisible()

    await page.getByTestId('btn-view-class').click()
    await expect(page.getByTestId('select-entity')).toHaveValue(/\d+/)
  })

  test('違反をクリックすると該当する対象へ移動する', async ({ page }) => {
    await createSchool(page, { name: 'E2E中学校7', type: '中学校', classesPerGrade: 1 })
    await solve(page)

    // 別の学級に切り替えてから違反を作る
    const [source, target] = await findTwoOccupiedCells(page)
    await dragTo(page, source.locator('.chip'), target)
    await expect(page.getByTestId('hard-count')).not.toHaveText('0')

    const beforeEntity = await page.getByTestId('select-entity').inputValue()
    // 教員別ビューへ移ってから違反行をクリックすると、クラス別へ戻ってくる
    await page.getByTestId('btn-view-teacher').click()
    await page.getByTestId('violation-H1').first().click()
    await expect(page.getByTestId('btn-view-class')).toHaveClass(/active/)
    await expect(page.getByTestId('select-entity')).toHaveValue(beforeEntity)
  })

  test('CSVを出力できる（クラス別・教員別）', async ({ page }) => {
    await createSchool(page, { name: 'E2E中学校8', type: '中学校', classesPerGrade: 1 })
    await solve(page)

    for (const testId of ['link-export-class', 'link-export-teacher']) {
      const [download] = await Promise.all([
        page.waitForEvent('download'),
        page.getByTestId(testId).click(),
      ])
      expect(download.suggestedFilename()).toMatch(/\.csv$/)
      const stream = await download.createReadStream()
      const chunks: Buffer[] = []
      for await (const chunk of stream) chunks.push(Buffer.from(chunk))
      const text = Buffer.concat(chunks).toString('utf8')
      expect(text).toContain('対象,曜日,1限')
      expect(text).toContain('月')
    }
  })

  test('小学校を作ると特別支援学級の交流授業が同じ講座になる', async ({ page }) => {
    await createSchool(page, {
      name: 'E2E小学校',
      type: '小学校',
      classesPerGrade: 1,
      specialNeeds: true,
    })
    await solve(page)

    await expect(page.getByTestId('hard-count')).toHaveText('0')

    // 特別支援学級のビューに切り替えると、体育などが通常学級と同じ講座で並ぶ
    await page.getByTestId('select-entity').selectOption({ label: '特別支援学級' })
    const chips = page.getByTestId('timetable-grid').locator('.chip')
    await expect.poll(async () => chips.count()).toBeGreaterThan(10)
  })

  test('高校の選択科目は同じコマに並列開講される', async ({ page }) => {
    await createSchool(page, { name: 'E2E高校', type: '高等学校', classesPerGrade: 1 })
    await solve(page)

    await expect(page.getByTestId('hard-count')).toHaveText('0')

    // 3年生は地歴選択と理科選択があるため、1つのコマに複数のチップが並ぶ
    await page.getByTestId('select-entity').selectOption({ label: '3年1組' })
    const grid = page.getByTestId('timetable-grid')
    const cells = grid.locator('[data-testid^="cell-"]')
    let multi = 0
    for (let i = 0; i < (await cells.count()); i++) {
      if ((await cells.nth(i).locator('.chip').count()) > 1) multi++
    }
    expect(multi).toBeGreaterThan(0)
  })

  test('学校を切り替えても状態が保たれる', async ({ page }) => {
    await createSchool(page, { name: 'E2E校A', type: '中学校', classesPerGrade: 1 })
    await solve(page)
    await expect(page.getByTestId('hard-count')).toHaveText('0')

    await page.getByTestId('btn-new-school').click()
    await createSchool(page, { name: 'E2E校B', type: '小学校', classesPerGrade: 1 })
    await solve(page)
    await expect(page.getByTestId('hard-count')).toHaveText('0')

    // 学校セレクタから元の学校に戻すと、その学校の時間割が復元される
    await page.getByTestId('select-school').selectOption({ label: 'E2E校A（中学校）' })
    await expect(page.getByTestId('timetable-grid')).toBeVisible()
    await expect(page.getByTestId('select-entity').locator('option').first()).toHaveText('1年1組')
  })
})
