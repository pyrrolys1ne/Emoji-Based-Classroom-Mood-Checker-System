import { test, expect } from '@playwright/test';

const user = {
  id: 'student-1',
  username: 'test-student',
  email: 'student@example.test',
  role: 'STUDENT',
  status: 'ACTIVE',
};
const envelope = (data: unknown) => ({ code: 'OK', message: 'ok', data });
const session = {
  id: 'session-1',
  courseId: 'course-1',
  courseName: '测试课堂',
  teacherName: '测试教师',
  className: '测试班',
  room: '测试教室',
  startsAt: new Date(Date.now() - 3600000).toISOString(),
  endsAt: new Date(Date.now() + 3600000).toISOString(),
  scheduledUserIds: [user.id],
};

test('API 登录 401 显示错误，不进入演示模式', async ({ page }) => {
  await page.route('**/api/auth/login', (route) =>
    route.fulfill({ status: 401, json: { code: 'UNAUTHORIZED', message: 'invalid', data: null } }),
  );
  await page.goto('/');
  await page.getByLabel('用户名').fill('test-student');
  await page.getByLabel('密码', { exact: true }).fill('password123');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('账号密码错误');
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible();
  await expect(page.getByRole('button', { name: '体验学生端' })).toHaveCount(0);
});

test('API 提交 501 保留选择且不显示成功或模拟记录', async ({ page }) => {
  let submits = 0;
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/login'))
      return route.fulfill({ json: envelope({ token: 'test-token', user }) });
    if (path.endsWith('/users/me')) return route.fulfill({ json: envelope(user) });
    if (path.endsWith('/sessions')) return route.fulfill({ json: envelope([session]) });
    if (path.endsWith('/emoji/history')) return route.fulfill({ json: envelope([]) });
    if (path.endsWith('/emoji') && route.request().method() === 'POST') {
      submits++;
      expect(route.request().postDataJSON()).toEqual({ sessionId: session.id, emotion: 'HAPPY' });
      return route.fulfill({
        status: 501,
        json: { code: 'NOT_IMPLEMENTED', message: 'not implemented', data: null },
      });
    }
    return route.fulfill({
      status: 404,
      json: { code: 'NOT_FOUND', message: 'not found', data: null },
    });
  });
  await page.goto('/');
  await page.getByLabel('用户名').fill(user.username);
  await page.getByLabel('密码', { exact: true }).fill('password123');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '课堂反馈' })).toBeVisible();
  await page.getByLabel('课堂', { exact: true }).selectOption(session.id);
  await page.getByRole('button', { name: '开心' }).click();
  await page.getByRole('button', { name: '提交反馈' }).click();
  await expect(page.getByRole('alert')).toContainText('尚未开放');
  await expect(page.getByRole('button', { name: '开心' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('还没有反馈记录。')).toBeVisible();
  expect(submits).toBe(1);
});
