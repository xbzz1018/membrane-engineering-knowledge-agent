import { expect, test } from '@playwright/test'

test('login screen exposes enterprise workbench boundary', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: '登录工作台' })).toBeVisible()
  await expect(page.getByText('审查结果可追溯')).toBeVisible()
  await expect(page.getByRole('button', { name: '进入工作台' })).toBeVisible()
})
