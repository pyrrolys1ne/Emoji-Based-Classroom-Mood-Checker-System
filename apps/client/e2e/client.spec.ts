import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const demoPassword = 'classroom-demo-2026';
const changedPassword = 'changed-demo-2026';
async function student(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: '体验学生端' }).click();
  await expect(page.getByRole('heading', { name: '课堂反馈' })).toBeVisible();
  await expect(page.getByLabel('课堂', { exact: true })).toBeEnabled();
  const current = page
    .getByLabel('课堂', { exact: true })
    .locator('option')
    .filter({ hasText: '演示课堂' });
  await page
    .getByLabel('课堂', { exact: true })
    .selectOption({ label: (await current.textContent()) ?? '' });
}
async function submitHappy(page: Page) {
  await page.getByRole('button', { name: '开心' }).click();
  await page.getByRole('button', { name: '提交反馈' }).click();
  await expect(
    page.getByRole('heading', { name: '最近的反馈' }).locator('..').getByText('开心'),
  ).toBeVisible();
}
async function checkA11y(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
}

test('学生提交、历史与刷新后恢复', async ({ page }) => {
  await student(page);
  await submitHappy(page);
  await page.getByRole('button', { name: '我的记录' }).click();
  await expect(page.getByRole('heading', { name: '我的记录' })).toBeVisible();
  await expect(page.getByText('开心', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: '我的记录' })).toBeVisible();
  await page.getByRole('button', { name: '我的记录' }).click();
  await expect(page.getByText('开心', { exact: true })).toBeVisible();
});

test('改密后使用新密码重新登录', async ({ page }) => {
  await student(page);
  await page.getByRole('button', { name: '账号', exact: true }).click();
  await page.getByLabel('当前密码').fill(demoPassword);
  await page.getByLabel('新密码', { exact: true }).fill(changedPassword);
  await page.getByLabel('确认新密码').fill(changedPassword);
  await page.getByRole('button', { name: '修改密码' }).click();
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible();
  await page.getByLabel('用户名').fill('student-a');
  await page.getByLabel('密码', { exact: true }).fill(changedPassword);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '课堂反馈' })).toBeVisible();
});

test('注册学生并登录', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '注册', exact: true }).click();
  await page.getByLabel('用户名').fill('new-student');
  await page.getByLabel('邮箱').fill('new-student@example.test');
  await page.getByLabel('密码', { exact: true }).fill(demoPassword);
  await page.getByLabel('确认密码').fill(demoPassword);
  await page.getByRole('button', { name: '注册', exact: true }).click();
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible();
  await page.getByLabel('用户名').fill('new-student');
  await page.getByLabel('密码', { exact: true }).fill(demoPassword);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '课堂反馈' })).toBeVisible();
});

test('教师查看课堂历史并筛选，整体分布保持不变', async ({ page }) => {
  await student(page);
  await submitHappy(page);
  await page.getByRole('button', { name: '退出', exact: true }).click();
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible();
  await page.getByRole('button', { name: '体验教师端' }).click();
  await expect(page.getByRole('heading', { name: '课堂记录' })).toBeVisible();
  await expect(page.getByLabel('课堂', { exact: true })).toBeEnabled();
  const current = page
    .getByLabel('课堂', { exact: true })
    .locator('option')
    .filter({ hasText: '演示课堂' });
  await page
    .getByLabel('课堂', { exact: true })
    .selectOption({ label: (await current.textContent()) ?? '' });
  const stats = page
    .locator('section')
    .filter({ has: page.getByRole('heading', { name: '课堂整体分布' }) });
  const history = page
    .locator('section')
    .filter({ has: page.getByRole('heading', { name: '课堂历史' }) });
  await expect(stats.getByText('共 1 条记录')).toBeVisible();
  await expect(history.getByText('开心', { exact: true })).toBeVisible();
  const filter = page.getByLabel('筛选记录');
  await expect(filter.locator('option')).toHaveCount(2);
  const id = await filter.locator('option').nth(1).getAttribute('value');
  await filter.selectOption(id!);
  await expect(history.getByText('开心', { exact: true })).toBeVisible();
  await expect(stats.getByText('共 1 条记录')).toBeVisible();
  const oldClass = page
    .getByLabel('课堂', { exact: true })
    .locator('option')
    .filter({ hasText: '历史课堂' });
  await page
    .getByLabel('课堂', { exact: true })
    .selectOption({ label: (await oldClass.textContent()) ?? '' });
  await expect(stats.getByText('共 0 条记录')).toBeVisible();
  await expect(history.getByText('所选范围暂无记录。')).toBeVisible();
});

test('登录、学生和教师页面的基础无障碍检查', async ({ page }) => {
  await page.goto('/');
  await checkA11y(page);
  await page.getByRole('button', { name: '体验学生端' }).click();
  await expect(page.getByRole('heading', { name: '课堂反馈' })).toBeVisible();
  await checkA11y(page);
  await page.getByRole('button', { name: '退出', exact: true }).click();
  await page.getByRole('button', { name: '体验教师端' }).click();
  await expect(page.getByRole('heading', { name: '课堂记录' })).toBeVisible();
  await checkA11y(page);
});

test('桌面、手机与窄屏没有横向溢出', async ({ page }, testInfo) => {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
    { width: 320, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto('/');
    await expect(page.getByRole('heading', { name: '登录' })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`login-${viewport.width}.png`),
      fullPage: true,
    });
    await page.getByRole('button', { name: '体验学生端' }).click();
    await expect(page.getByRole('heading', { name: '课堂反馈' })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`student-${viewport.width}.png`),
      fullPage: true,
    });
    await page.getByRole('button', { name: '退出', exact: true }).click();
    await page.getByRole('button', { name: '体验教师端' }).click();
    await expect(page.getByRole('heading', { name: '课堂记录' })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`teacher-${viewport.width}.png`),
      fullPage: true,
    });
    await page.getByRole('button', { name: '退出', exact: true }).click();
  }
});
