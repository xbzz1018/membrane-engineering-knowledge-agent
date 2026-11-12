import { writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import { chromium, expect } from '@playwright/test'

const runtime = resolve('..', 'data', 'runtime')
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
  const token = await page.evaluate(() => sessionStorage.getItem('membrane.access_token'))
  const headers = { Authorization: `Bearer ${token}` }
  const base = 'http://127.0.0.1:8080/api/v1'
  const projectResponse = await page.request.post(`${base}/projects`, { headers, data: { name: 'SYNTHETIC 浏览器检索 ' + Date.now() } })
  expect(projectResponse.ok()).toBeTruthy()
  const project = await projectResponse.json()
  const ids = []
  for (const model of ['PTFE-502', 'PTFE-5020']) {
    const uploaded = await page.request.post(`${base}/documents/upload`, { headers, multipart: {
      project_id: project.id, data_classification: 'public', parse_method: 'text',
      file: { name: `${model}-browser.txt`, mimeType: 'text/plain', buffer: Buffer.from(`SYNTHETIC 材料规格 ${model} 名义厚度 0.8 mm`) },
    } })
    expect(uploaded.ok()).toBeTruthy()
    const doc = await uploaded.json()
    ids.push(doc.document_id)
    expect((await page.request.post(`${base}/documents/${doc.document_id}/index`, { headers })).ok()).toBeTruthy()
    await expect.poll(async () => (await (await page.request.get(`${base}/documents/${doc.document_id}`, { headers })).json()).status, { timeout: 60000 }).toBe('indexed')
  }
  await page.evaluate(pid => sessionStorage.setItem('membrane.project_id', pid), project.id)
  await page.goto('http://127.0.0.1:5173/documents')
  const row = page.getByRole('row').filter({ hasText: 'PTFE-502-browser.txt' })
  await row.getByRole('button', { name: '业务条件', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '资料业务条件' })
  await expect(dialog.getByLabel('工程型号')).toBeEnabled()
  await dialog.getByLabel('工程型号').fill('PTFE-502')
  await dialog.getByLabel('适用版次').fill('R2')
  await dialog.getByLabel('声明依据').fill('SYNTHETIC 浏览器验收：规格正文型号说明')
  await dialog.getByLabel('生效开始日期').fill('2026-01-01')
  await dialog.getByLabel('生效开始日期').press('Tab')
  await dialog.getByLabel('生效结束日期').fill('2026-12-31')
  await dialog.getByLabel('生效结束日期').press('Tab')
  const saved = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().endsWith('/business-metadata') && r.ok())
  await dialog.getByRole('button', { name: '保存条件' }).click()
  await saved
  await expect(dialog).toBeHidden()
  // Declare the near model through HTTP so exact search must distinguish it.
  const other = await (await page.request.get(`${base}/documents/${ids[1]}`, { headers })).json()
  const declared = await page.request.put(`${base}/documents/${ids[1]}/business-metadata`, { headers, data: {
    engineering_model: 'PTFE-5020', applicable_revision: 'R2', document_type: 'other',
    effective_from: '2026-01-01', effective_to: '2026-12-31', source_note: 'SYNTHETIC 近似型号排除', expected_lock_version: other.lock_version,
  } })
  expect(declared.ok()).toBeTruthy()
  const search = page.getByRole('region', { name: '条件检索' })
  await search.getByLabel('工程型号').fill('PTFE-502')
  await search.getByLabel('适用版次').fill('R2')
  await search.getByRole('button', { name: '检索资料' }).click()
  await expect(search.locator('.evidence-item')).toHaveCount(1)
  await expect(search.locator('.evidence-item')).toContainText('PTFE-502-browser.txt')
  await search.getByRole('button', { name: '查看证据' }).click()
  await expect(page.locator('.el-drawer')).toContainText('名义厚度 0.8 mm')
  await page.locator('.el-drawer__close-btn').click()
  await row.getByRole('button', { name: '业务条件', exact: true }).click()
  await expect(dialog.getByLabel('工程型号')).toHaveValue('PTFE-502')
  const snapshot = await (await page.request.get(`${base}/documents/${ids[0]}`, { headers })).json()
  expect((await page.request.put(`${base}/documents/${ids[0]}/business-metadata`, { headers, data: {
    engineering_model: 'PTFE-502', applicable_revision: 'R2', document_type: 'other',
    effective_from: '2026-01-01', effective_to: '2026-12-31', source_note: 'SYNTHETIC 并发修改', expected_lock_version: snapshot.lock_version,
  } })).ok()).toBeTruthy()
  const conflict = page.waitForResponse(r => r.request().method() === 'PUT' && r.status() === 409)
  await dialog.getByRole('button', { name: '保存条件' }).click()
  await conflict
  await expect(dialog.getByRole('alert')).toContainText('资料版本已变化')
  await expect(dialog.getByRole('button', { name: '保存条件' })).toBeDisabled()
  await dialog.getByRole('button', { name: '重新加载' }).click()
  await expect(dialog.getByRole('button', { name: '保存条件' })).toBeEnabled()
  await expect(dialog.getByLabel('声明依据')).toHaveValue('SYNTHETIC 并发修改')
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(page.locator('.el-overlay').filter({ visible: true })).toHaveCount(0)
  await page.screenshot({ path: resolve(runtime, 'documents-search.png'), fullPage: true, animations: 'disabled' })
  await search.getByLabel('工程型号').fill('NO-ANSWER')
  await search.getByRole('button', { name: '检索资料' }).click()
  await expect(search.getByRole('status')).toContainText('没有符合条件')
  await expect(search.locator('.evidence-item')).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: resolve(runtime, 'documents-mobile.png'), fullPage: true, animations: 'disabled' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  if (errors.length) throw new Error(JSON.stringify(errors))
  const result = { validated_at: new Date().toISOString(), mode: 'real browser / HTTP / local fake model; actual document status polled',
    project_id: project.id, document_ids: ids, checks: { metadata_save_reload: 'passed', exact_model_search: 'passed',
      evidence_drawer: 'passed', stale_save_409: 'passed', conflict_reload: 'passed', no_answer: 'passed',
      mobile_no_horizontal_overflow: 'passed' }, page_errors: errors }
  await writeFile(resolve(runtime, 'documents-browser-acceptance.json'), JSON.stringify(result, null, 2))
  process.stdout.write(JSON.stringify(result) + '\n')
} finally {
  await browser.close()
}
