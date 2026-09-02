import { defineConfig, devices } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'

// この環境には Chromium が焼き込まれている（PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers）。
// @playwright/test のバージョンによって期待するリビジョンが変わるため、
// ブラウザが用意されている場合は実体を直接指す。
const BUNDLED_CHROMIUM = '/opt/pw-browsers/chromium'
const executablePath = fs.existsSync(BUNDLED_CHROMIUM) ? BUNDLED_CHROMIUM : undefined

// E2E は毎回まっさらなDBで動かす。求解結果が前回の実行に影響されないようにするため。
const DB_PATH = path.join(os.tmpdir(), `timetable-e2e-${process.env.PW_DB_TAG ?? 'default'}.db`)

export default defineConfig({
  testDir: './tests',
  // 求解ジョブを含むため、既定より長めに取る
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  // 単一のバックエンドプロセス（＝インプロセスのジョブ表とSQLite）を共有するため直列実行
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    // 既定は無制限。要素が現れないまま待ち続けてテスト全体のタイムアウトを
    // 食い潰すのを避けるため、操作単位でも上限を設ける
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'ja-JP',
    timezoneId: 'Asia/Tokyo',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // 時間割グリッドと未配置トレイを同時に画面へ収める。ドラッグ中に
        // スクロールが挟まると座標がずれて掴み損ねるため、縦を広く取る
        viewport: { width: 1440, height: 1400 },
        launchOptions: { executablePath },
      },
    },
  ],
  webServer: [
    {
      command: 'python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000',
      cwd: path.join(__dirname, '..', 'backend'),
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        TIMETABLE_DATABASE_URL: `sqlite:///${DB_PATH}`,
        TIMETABLE_E2E_RESET: '1',
      },
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173',
      cwd: path.join(__dirname, '..', 'frontend'),
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
