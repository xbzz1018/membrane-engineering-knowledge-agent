import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import { chromium, expect } from '@playwright/test'

const runtime = resolve('..', 'data', 'runtime')
const acceptance = JSON.parse(await readFile(resolve(runtime, 'demo-acceptance.json'), 'utf8'))
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('http://127.0.0.1:5173/login')
  await page.locator('input[autocomplete="username"]').fill('admin')
  await page.locator('input[autocomplete="current-password"]').fill('admin-change-me')
  await page.getByRole('button', { name: '进入工作台' }).click()
  await page.waitForURL('**/dashboard')
  await page.goto(`http://127.0.0.1:5173/reviews/${acceptance.review_id}`)
  await expect(page.getByRole('heading', { name: '工程问题单' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '证据引用' })).toBeVisible()
  await expect(page.getByText('A120-design-demo.txt', { exact: true })).toBeVisible()
  await expect(page.getByText('PTFE502-material-demo.txt', { exact: true })).toBeVisible()
  await expect(page.locator('.el-tag').first()).toContainText('待审批')
  await page.screenshot({ path: resolve(runtime, 'demo-review.png'), fullPage: true, animations: 'disabled' })
  // Use a separate synthetic report so the main demo remains pending.
  const token = await page.evaluate(() => sessionStorage.getItem('membrane.access_token'))
  const created = await page.request.post('http://127.0.0.1:8080/api/v1/package-reviews', {
    headers: { Authorization: `Bearer ${token}` },
    data: { project_id: 'demo-project', document_ids: acceptance.document_ids, review_mode: 'full' },
  })
  expect(created.ok()).toBeTruthy()
  const copy = await created.json()
  await page.goto(`http://127.0.0.1:5173/reviews/${copy.review_id}`)
  await page.getByRole('button', { name: '批准', exact: true }).click()
  const blocked = page.waitForResponse(r => r.url().endsWith('/decision') && r.status() === 409)
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await blocked
  await expect(page.getByText('仍有需要人工处理的问题，先逐条解决或忽略后再批准', { exact: true })).toBeVisible()
  for (let i = 0; i < copy.issues.length; i += 1) {
    await page.getByRole('button', { name: '忽略', exact: true }).nth(i).click()
    const dialog = page.getByRole('dialog', { name: '处理说明' })
    await dialog.getByRole('textbox').fill('SYNTHETIC 浏览器验收：已核对差异，本次仅验证操作闭环')
    const updated = page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().includes('/issues/') && r.ok())
    await dialog.getByRole('button', { name: '确定', exact: true }).click()
    await updated
    await expect(dialog).toBeHidden()
  }
  await page.getByRole('button', { name: '批准', exact: true }).click()
  const approved = page.waitForResponse(r => r.url().endsWith('/decision') && r.ok())
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await approved
  await expect(page.locator('.review-summary .el-tag')).toContainText('已批准')
  await expect(page.getByRole('button', { name: '忽略', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '批准', exact: true })).toHaveCount(0)
  if (errors.length) throw new Error(JSON.stringify(errors))
  const result = {
    validated_at: new Date().toISOString(), login: 'passed', review_page: 'passed', evidence_files: 'passed',
    unresolved_approval_409: 'passed', dismissal_reason: 'passed', approval: 'passed',
    terminal_actions_hidden: 'passed', approved_review_id: copy.review_id, page_errors: errors,
  }
  await writeFile(resolve(runtime, 'browser-acceptance.json'), JSON.stringify(result, null, 2))
  process.stdout.write(`${JSON.stringify(result)}\n`)
} finally {
  await browser.close()
}
