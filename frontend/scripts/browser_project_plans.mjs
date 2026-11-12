import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import { chromium, expect } from '@playwright/test'

const base = process.env.PLAN_ACCEPTANCE_API || 'http://127.0.0.1:18080'
const frontend = process.env.PLAN_ACCEPTANCE_FRONTEND || 'http://127.0.0.1:5173'
const output = resolve('..', 'data/runtime/project-plan-browser')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const summary = {
  mode: 'real Chromium / Local HTTP API / explicitly configured backend',
  api_url: base,
  frontend_url: frontend,
  checks: {},
  errors: [],
}
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 }, acceptDownloads: true })
  page.on('pageerror', error => summary.errors.push(error.message))
  // Reuse the development frontend and direct API requests to the selected
  // acceptance backend. Every run creates its own synthetic project.
  await page.route('http://127.0.0.1:8080/**', route => route.continue({
    url: route.request().url().replace('http://127.0.0.1:8080', base),
  }))
  await page.goto(frontend + '/login')
  await page.locator('input[autocomplete="username"]').fill('admin')
  await page.locator('input[autocomplete="current-password"]').fill('admin-change-me')
  await page.getByRole('button', { name: '进入工作台' }).click()
  await page.waitForURL('**/dashboard')
  const token = await page.evaluate(() => sessionStorage.getItem('membrane.access_token'))
  const headers = { Authorization: `Bearer ${token}` }
  const projectResponse = await page.request.post(base + '/api/v1/projects', { headers, data: { name: 'SYNTHETIC 方案浏览器验收 ' + Date.now() } })
  expect(projectResponse.ok()).toBeTruthy()
  const project = await projectResponse.json()
  const uploaded = await page.request.post(base + '/api/v1/documents/upload', { headers, multipart: {
    project_id: project.id, data_classification: 'public', parse_method: 'text',
    file: { name: 'synthetic-plan-history.txt', mimeType: 'text/plain', buffer: Buffer.from(
      'SYNTHETIC 停车棚历史项目案例。材料型号PVDF-Z901，适用版次R1，名义厚度0.8 mm。仅用于功能测试，非实际项目。',
    ) },
  } })
  expect(uploaded.ok()).toBeTruthy()
  const document = await uploaded.json()
  expect((await page.request.post(`${base}/api/v1/documents/${document.document_id}/index`, { headers })).ok()).toBeTruthy()
  await expect.poll(async () => (await (await page.request.get(`${base}/api/v1/documents/${document.document_id}`, { headers })).json()).status,
    { timeout: 60000 }).toBe('indexed')
  await page.evaluate(projectId => sessionStorage.setItem('membrane.project_id', projectId), project.id)
  await page.goto(frontend + '/chat')
  await page.getByPlaceholder('输入工程资料问题，Enter 发送，Shift+Enter 换行').fill(
    '生成800平方米PVDF-Z901停车棚初步方案，地点：合成浏览器场地',
  )
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const view = page.getByRole('button', { name: '查看方案与复核' })
  await expect(view).toBeVisible({ timeout: 45000 })
  await view.click()
  const panel = page.getByRole('dialog', { name: '项目初步方案', exact: true })
  await expect(panel).toContainText('待审批', { timeout: 60000 })
  await expect(panel).toContainText('PVDF-Z901')
  await expect(panel.getByRole('button', { name: '生成 Markdown 和 Word' })).toHaveCount(0)
  summary.checks.chat_create_and_review = true
  await page.screenshot({ path: resolve(output, 'plan-awaiting-approval.png'), fullPage: true, animations: 'disabled' })

  await panel.getByRole('button', { name: '批准当前版本', exact: true }).click()
  const approve = page.getByRole('dialog', { name: '批准当前方案', exact: true })
  await approve.getByRole('textbox').fill('SYNTHETIC 人工核对当前版本的需求与来源')
  await approve.getByRole('button', { name: '确认', exact: true }).click()
  await expect(panel).toContainText('已批准', { timeout: 45000 })
  await panel.getByRole('button', { name: '生成 Markdown 和 Word' }).click()
  await expect(panel.getByRole('button', { name: 'DOCX · 下载' })).toBeEnabled({ timeout: 20000 })
  const downloadEvent = page.waitForEvent('download')
  await panel.getByRole('button', { name: 'DOCX · 下载' }).click()
  const download = await downloadEvent
  await download.saveAs(resolve(output, 'approved-plan.docx'))
  summary.checks.same_version_approval_and_word_download = true

  const plans = await (await page.request.get(`${base}/api/v1/projects/${project.id}/plans`, { headers })).json()
  const first = plans[0]
  const oldFile = first.artifacts.find(item => item.format === 'docx')
  await panel.getByRole('button', { name: '修改形成新版本' }).click()
  await panel.getByLabel('项目地点', { exact: true }).fill('另一合成场地')
  await panel.getByPlaceholder('填写修订原因').fill('SYNTHETIC 修改地点验证重新审查')
  await panel.getByRole('button', { name: '保存新版本并审查' }).click()
  await expect(panel).toContainText('v2')
  await expect(panel).toContainText('待审批', { timeout: 60000 })
  await expect(panel.getByRole('button', { name: '生成 Markdown 和 Word' })).toHaveCount(0)
  const denied = await page.request.get(base + oldFile.download_url, { headers })
  expect(denied.status()).toBe(409)
  summary.checks.revision_requires_new_approval_and_old_download_denied = true

  await panel.getByRole('button', { name: '退回', exact: true }).click()
  const reject = page.getByRole('dialog', { name: '退回当前方案', exact: true })
  await reject.getByRole('button', { name: '取消', exact: true }).click()
  await expect(panel).toContainText('待审批')
  summary.checks.cancel_dialog_does_not_submit_decision = true
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: resolve(output, 'plan-mobile.png'), fullPage: true, animations: 'disabled' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  summary.checks.mobile_no_horizontal_overflow = true
  expect(summary.errors).toEqual([])
  summary.plan_id = first.plan_id
  summary.project_id = project.id
  summary.all_passed = true
} catch (error) {
  summary.all_passed = false
  summary.error = String(error)
  throw error
} finally {
  summary.finished_at = new Date().toISOString()
  await writeFile(resolve(output, 'summary.json'), JSON.stringify(summary, null, 2))
  process.stdout.write(JSON.stringify(summary) + '\n')
  await browser.close()
}
