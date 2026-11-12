import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import { chromium, expect } from '@playwright/test'

const runtime = resolve('..', 'data', 'runtime')
const seeded = JSON.parse(await readFile(resolve(runtime, 'temporal-demo-acceptance.json'), 'utf8'))
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('http://127.0.0.1:5173/login')
  await page.locator('input[autocomplete="username"]').fill('admin')
  await page.locator('input[autocomplete="current-password"]').fill('admin-change-me')
  await page.getByRole('button', { name: '进入工作台' }).click()
  await page.waitForURL('**/dashboard')
  await page.goto(`http://127.0.0.1:5173/reviews/${seeded.review_id}`)
  await expect(page.locator('.review-summary .el-tag')).toContainText('待审批')
  await page.screenshot({ path: resolve(runtime, 'temporal-review.png'), fullPage: true, animations: 'disabled' })
  const token = await page.evaluate(() => sessionStorage.getItem('membrane.access_token'))
  const created = await page.request.post('http://127.0.0.1:8080/api/v1/package-reviews', {
    headers: { Authorization: `Bearer ${token}` },
    data: { project_id: 'demo-project', document_ids: seeded.document_ids, review_mode: 'full' },
  })
  expect(created.ok()).toBeTruthy()
  const review = await created.json()
  expect(review.status).toBe('queued')
  await page.goto(`http://127.0.0.1:5173/reviews/${review.review_id}`)
  await expect(page.locator('.review-summary .el-tag')).toContainText('待审批', { timeout: 30000 })
  await page.getByRole('button', { name: '退回', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '退回审查' })
  await dialog.getByRole('textbox').fill('SYNTHETIC 浏览器：请补充厚度差异依据')
  const decision = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/decision') && r.ok())
  await dialog.getByRole('button', { name: '确认退回' }).click()
  expect((await (await decision).json()).status).toBe('decision_pending')
  await expect(page.locator('.review-summary .el-tag')).toContainText('已退回', { timeout: 40000 })
  await expect(page.getByRole('button', { name: '批准', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '取消', exact: true })).toHaveCount(0)
  if (errors.length) throw new Error(JSON.stringify(errors))
  const result = { validated_at: new Date().toISOString(), mode: 'real browser / real Temporal / Fake Agents',
    checks: { persisted_report_after_server_restart: 'passed', submission_queued: 'passed', automatic_report_refresh: 'passed',
      decision_pending: 'passed', automatic_final_state_refresh: 'passed', terminal_actions_hidden: 'passed' },
    reviewed_copy_id: review.review_id, retained_demo_id: seeded.review_id, page_errors: errors }
  await writeFile(resolve(runtime, 'temporal-browser-acceptance.json'), JSON.stringify(result, null, 2))
  process.stdout.write(JSON.stringify(result) + '\n')
} finally {
  await browser.close()
}
