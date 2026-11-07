import { chromium, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

const fixtures = JSON.parse(process.env.MOOD_ACCEPTANCE_FIXTURES);
const urls = JSON.parse(process.env.MOOD_ACCEPTANCE_URLS);
const password = 'synthetic-acceptance-password';
const classroom = fixtures.sessions[0];
const browser = await chromium.launch({ headless: true });
const contexts = [];
async function page() {
  const context = await browser.newContext();
  contexts.push(context);
  return context.newPage();
}
async function login(target, username, admin = false, secret = password) {
  await target.goto(admin ? urls.admin : urls.client);
  await target.getByLabel('用户名', { exact: true }).fill(username);
  await target.getByLabel('密码', { exact: true }).fill(secret);
  await target.getByRole('button', { name: admin ? '登录工作空间' : '登录', exact: true }).click();
  if (admin) await expect(target.getByText('实时通道已连接', { exact: true })).toBeVisible();
  else await expect(target.getByRole('button', { name: '退出', exact: true })).toBeVisible();
  await expect(target.getByText('演示模式', { exact: true })).toHaveCount(0);
}
async function request(target, method, path, token, data, key) {
  return target.request.fetch(urls.backend + '/api' + path, {
    method,
    headers: { Authorization: 'Bearer ' + token, ...(key ? { 'Idempotency-Key': key } : {}) },
    data,
  });
}
async function value(target, method, path, token, data, key) {
  const response = await request(target, method, path, token, data, key);
  expect(response.status()).toBe(200);
  return (await response.json()).data;
}
async function clientToken(target) {
  return target.evaluate(() => JSON.parse(sessionStorage.getItem('mood-client-auth-api')).token);
}

try {
  if (process.env.MOOD_ACCEPTANCE_PHASE === 'restore') {
    const target = await page();
    await login(target, 'acceptance-student', false, password + '-changed');
    await target.getByLabel('课堂', { exact: true }).selectOption(classroom.id);
    const records = await value(target, 'GET', '/emoji/history', await clientToken(target));
    expect(records).toHaveLength(12);
    await expect(target.locator('.record-list')).toContainText('手动反馈');
    await target.reload();
    await expect(target.getByRole('button', { name: '退出', exact: true })).toBeVisible();
    console.log('通过：重启后生产构建页面重新登录、个人历史与刷新恢复。');
  } else {
    const invitedAdmin = await page();
    const invitation = await value(
      invitedAdmin,
      'POST',
      '/admin/invitations',
      fixtures.admin.token,
      { expiresInHours: 1 },
    );
    await invitedAdmin.goto(urls.admin);
    await invitedAdmin.getByRole('button', { name: '管理员注册', exact: true }).click();
    await invitedAdmin.getByLabel('用户名', { exact: true }).fill('browser-admin');
    await invitedAdmin.getByLabel('邮箱', { exact: true }).fill('browser-admin@example.edu');
    await invitedAdmin.getByLabel('密码', { exact: true }).fill(password);
    await invitedAdmin.getByLabel('确认密码', { exact: true }).fill(password);
    await invitedAdmin.getByLabel('邀请码', { exact: true }).fill(invitation.code);
    await invitedAdmin.getByRole('button', { name: '注册管理员', exact: true }).click();
    await expect(invitedAdmin.getByText('管理员注册成功，请登录。', { exact: true })).toBeVisible();
    await login(invitedAdmin, 'browser-admin', true);
    await invitedAdmin.getByRole('button', { name: '用户管理', exact: true }).click();
    await invitedAdmin.getByRole('button', { name: '生成管理员邀请码', exact: true }).click();
    await expect(invitedAdmin.getByLabel('一次性邀请码', { exact: true })).toBeVisible();
    await invitedAdmin.getByRole('button', { name: '退出登录', exact: true }).click();
    console.log('通过：管理员一次性邀请注册、真实登录与管理员生成邀请码。');
    const student = await page();
    const registered = await page();
    await registered.goto(urls.client);
    await registered.getByRole('button', { name: '注册', exact: true }).click();
    await registered.getByLabel('用户名', { exact: true }).fill('browser-registered');
    await registered.getByLabel('邮箱', { exact: true }).fill('browser-registered@example.edu');
    await registered.getByLabel('密码', { exact: true }).fill(password);
    await registered.getByLabel('确认密码', { exact: true }).fill(password);
    await registered.getByRole('button', { name: '注册', exact: true }).click();
    await expect(registered.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
    await login(registered, 'browser-registered');
    await expect(
      registered.getByText('暂无课堂，请联系老师安排课堂。', { exact: true }),
    ).toBeVisible();
    const outsider = await clientToken(registered);
    expect(
      (
        await request(
          registered,
          'POST',
          '/emoji',
          outsider,
          { sessionId: classroom.id, emotion: 'HAPPY' },
          'outsider-feedback',
        )
      ).status(),
    ).toBe(403);

    await login(student, 'acceptance-student');
    await student.getByLabel('课堂', { exact: true }).selectOption(classroom.id);
    await student.getByRole('button', { name: '开心', exact: true }).click();
    await student.context().setOffline(true);
    await student.getByRole('button', { name: '提交反馈', exact: true }).click();
    await expect(student.getByRole('alert')).toContainText('网络连接失败');
    await expect(student.getByText('反馈已保存。', { exact: true })).toHaveCount(0);
    await student.context().setOffline(false);
    const submitted = student.waitForResponse((response) => response.url().endsWith('/api/emoji'));
    await student.getByRole('button', { name: '提交反馈', exact: true }).click();
    const original = (await (await submitted).json()).data;
    await expect(student.getByText('反馈已保存。', { exact: true })).toBeVisible();
    const token = await clientToken(student);
    expect(original.userId).toBe(fixtures.users['acceptance-student'].id);
    expect(original.source).toBe('MANUAL');
    for (let index = 0; index < 10; index++) {
      await value(
        student,
        'POST',
        '/emoji',
        token,
        { sessionId: classroom.id, emotion: index === 9 ? 'SAD' : 'HAPPY' },
        'acceptance-manual-' + index,
      );
    }
    let uncertainKey;
    let uncertainRecord;
    await student.route(
      '**/api/emoji',
      async (route) => {
        uncertainKey = route.request().headers()['idempotency-key'];
        const response = await route.fetch();
        expect(response.status()).toBe(200);
        uncertainRecord = (await response.json()).data;
        await route.abort('failed');
      },
      { times: 1 },
    );
    await student.getByRole('button', { name: '开心', exact: true }).click();
    await student.getByRole('button', { name: '提交反馈', exact: true }).click();
    await expect(student.getByRole('alert')).toContainText('请先查看历史核实结果');
    const retried = student.waitForRequest(
      (req) => req.method() === 'POST' && req.url().endsWith('/api/emoji'),
    );
    const retryResponse = student.waitForResponse((res) => res.url().endsWith('/api/emoji'));
    await student.getByRole('button', { name: '提交反馈', exact: true }).click();
    expect((await retried).headers()['idempotency-key']).toBe(uncertainKey);
    expect((await (await retryResponse).json()).data.id).toBe(uncertainRecord.id);
    const history = await value(student, 'GET', '/emoji/history', token);
    expect(history).toHaveLength(12);
    expect(history.map((record) => record.id)).toContain(original.id);
    await student.reload();
    await expect(student.locator('.record-list')).toContainText('手动反馈');
    console.log('通过：注册、名单授权、断网拒绝假成功、真实反馈、丢失回执同键重试及刷新历史。');

    const other = await page();
    await login(other, 'other-student');
    const otherToken = await clientToken(other);
    expect(
      (
        await request(other, 'GET', '/emoji/history?userId=' + original.userId, otherToken)
      ).status(),
    ).toBe(403);
    expect(
      (
        await request(
          other,
          'POST',
          '/emoji',
          otherToken,
          { sessionId: classroom.id, emotion: 'NEUTRAL' },
          'other-forbidden',
        )
      ).status(),
    ).toBe(403);
    await value(
      other,
      'POST',
      '/emoji',
      otherToken,
      { sessionId: fixtures.sessions[1].id, emotion: 'NEUTRAL' },
      'other-valid',
    );
    expect(await value(other, 'GET', '/emoji/history', otherToken)).toHaveLength(1);
    expect((await request(other, 'GET', '/admin/users', otherToken)).status()).toBe(403);

    const ai = await value(
      student,
      'POST',
      '/ai/emoji-results',
      process.env.MOOD_AI_SERVICE_TOKEN,
      {
        sessionId: classroom.id,
        emotion: 'HAPPY',
        confidence: 0.8,
        recordedAt: new Date().toISOString(),
        deviceId: '=CAMERA_TEST',
        simulated: true,
        inferenceProvider: 'DeepSeek',
        confidenceKind: 'self_reported',
      },
      'acceptance-ai-result',
    );
    expect(ai.record.userId).toBeNull();
    const teacher = await page();
    await login(teacher, 'acceptance-teacher');
    const teacherToken = await clientToken(teacher);
    const secondTeacher = await value(teacher, 'POST', '/auth/login', '', {
      username: 'other-teacher',
      password,
    });
    expect(
      (await value(teacher, 'GET', '/sessions', secondTeacher.token)).map((session) => session.id),
    ).toEqual([fixtures.sessions[1].id]);
    expect(
      (
        await request(
          teacher,
          'GET',
          '/emoji/history?sessionId=' + classroom.id,
          secondTeacher.token,
        )
      ).status(),
    ).toBe(403);
    expect(
      (
        await request(
          teacher,
          'GET',
          '/emoji/history?sessionId=' + fixtures.sessions[1].id,
          teacherToken,
        )
      ).status(),
    ).toBe(403);
    expect((await request(teacher, 'GET', '/admin/emoji/export', teacherToken)).status()).toBe(403);
    const stats = teacher.getByRole('region', { name: '课堂整体分布' });
    await expect(stats.getByText('共 12 条记录', { exact: true })).toBeVisible();
    await teacher.getByLabel('统计来源', { exact: true }).selectOption('AI');
    await expect(stats.getByText('共 1 条记录', { exact: true })).toBeVisible();
    await teacher.getByLabel('统计来源', { exact: true }).selectOption('ALL');
    await expect(stats.getByText('共 13 条记录', { exact: true })).toBeVisible();
    console.log('通过：两名学生与两名教师的数据范围、管理员接口门禁、匿名 AI 和教师来源统计。');

    const admin = await page();
    const frames = [];
    const sockets = [];
    admin.on('websocket', (socket) => {
      if (!new URL(socket.url()).pathname.endsWith('/ws/dashboard')) return;
      sockets.push(socket);
      socket.on('framereceived', (event) => frames.push(JSON.parse(event.payload.toString())));
    });
    await login(admin, 'acceptance-admin', true);
    await admin.getByRole('button', { name: '多维统计', exact: true }).click();
    await expect(admin.getByText('当前筛选共 13 条情绪记录', { exact: true })).toBeVisible();
    await admin.getByLabel('统计来源').selectOption('ALL');
    await expect(admin.getByText('当前筛选共 14 条情绪记录', { exact: true })).toBeVisible();
    const aggregate = await value(
      admin,
      'GET',
      '/admin/statistics?source=ALL',
      fixtures.admin.token,
    );
    expect(aggregate.timeline.reduce((sum, bucket) => sum + bucket.total, 0)).toBe(14);
    expect(aggregate.groups.reduce((sum, group) => sum + group.total, 0)).toBe(14);
    await admin.getByRole('button', { name: '情绪记录', exact: true }).click();
    await admin.getByLabel('筛选来源').selectOption('ALL');
    await admin.getByLabel('筛选情绪').selectOption('HAPPY');
    await expect(admin.locator('tbody tr')).toHaveCount(10);
    const downloading = admin.waitForEvent('download');
    await admin.getByRole('button', { name: '导出 CSV', exact: true }).click();
    const bytes = await readFile(await (await downloading).path());
    expect(bytes.subarray(0, 3).equals(Buffer.from([0xef, 0xbb, 0xbf]))).toBe(true);
    const csv = bytes.toString('utf8');
    expect(csv.split('\r\n').filter(Boolean)).toHaveLength(13);
    expect(csv).toContain(original.id);
    expect(csv).toContain('self_reported');
    expect(csv).toContain("'=CAMERA_TEST");
    expect(csv).not.toContain('"SAD"');
    expect(csv).not.toContain('"NEUTRAL"');
    const teacherRecords = await value(teacher, 'GET', '/emoji/history', teacherToken);
    expect(teacherRecords.map((record) => record.id)).toContain(original.id);
    console.log('通过：同一记录跨端一致、服务端全量分布/趋势/分组、分页后完整 CSV 与公式防护。');

    const teacherAdmin = await page();
    await login(teacherAdmin, 'acceptance-teacher', true);
    await teacherAdmin.getByRole('button', { name: '情绪记录', exact: true }).click();
    await teacherAdmin.getByLabel('筛选来源').selectOption('AI');
    await admin.getByRole('button', { name: 'AI 集成', exact: true }).click();
    await expect(admin.getByText('API 未配置', { exact: true })).toBeVisible();
    await admin.getByLabel('关联课堂').selectOption(classroom.id);
    await admin.getByLabel('采样间隔（秒）').fill('0.5');
    const started = admin.waitForResponse((response) => response.url().endsWith('/admin/ai/start'));
    await admin.getByRole('button', { name: '启动采集', exact: true }).click();
    expect((await started).status()).toBe(200);
    await expect.poll(() => frames.at(-1)?.total).toBeGreaterThan(14);
    await expect.poll(() => teacherAdmin.locator('tbody tr').count()).toBeGreaterThan(1);
    const stopped = admin.waitForResponse((response) => response.url().endsWith('/admin/ai/stop'));
    await admin.getByRole('button', { name: '停止采集', exact: true }).click();
    expect((await stopped).status()).toBe(200);
    const before = frames.at(-1).version;
    await value(admin, 'PUT', '/admin/courses/' + classroom.courseId, fixtures.admin.token, {
      name: '验收更正课程',
      teacherId: fixtures.users['acceptance-teacher'].id,
    });
    await expect.poll(() => frames.at(-1)?.version).not.toBe(before);
    await expect(teacherAdmin.locator('tbody')).toContainText('验收更正课程');
    const socketUrl = new URL(sockets.at(-1).url());
    expect([...socketUrl.searchParams.keys()]).toEqual(['ticket']);
    expect(socketUrl.searchParams.get('ticket')).toMatch(/^wst_/);
    expect(
      frames.every(
        (frame) => Object.keys(frame).sort().join(',') === 'latestId,total,type,version',
      ),
    ).toBe(true);
    await admin.getByRole('button', { name: '退出登录', exact: true }).click();
    await expect(
      admin.getByRole('heading', { name: '欢迎回到课堂心晴', exact: true }),
    ).toBeVisible();
    await expect.poll(() => sockets.at(-1).isClosed()).toBe(true);
    await expect(teacherAdmin.getByText('实时通道已连接', { exact: true })).toBeVisible();
    console.log(
      '通过：短票据 WebSocket、实际 AI 服务模拟启停、教师自动刷新、版本通知和退出撤销连接。',
    );

    const secondLogin = await value(student, 'POST', '/auth/login', '', {
      username: 'acceptance-student',
      password,
    });
    await student.getByRole('button', { name: '账号', exact: true }).click();
    await student.getByLabel('当前密码', { exact: true }).fill(password);
    await student.getByLabel('新密码', { exact: true }).fill(password + '-changed');
    await student.getByLabel('确认新密码', { exact: true }).fill(password + '-changed');
    await student.getByRole('button', { name: '修改密码', exact: true }).click();
    await expect(student.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
    for (const revoked of [token, secondLogin.token]) {
      expect((await request(student, 'GET', '/users/me', revoked)).status()).toBe(401);
    }
    await login(student, 'acceptance-student', false, password + '-changed');
    const changedToken = await clientToken(student);
    const loggedOut = student.waitForResponse((response) =>
      response.url().endsWith('/api/auth/logout'),
    );
    await student.getByRole('button', { name: '退出', exact: true }).click();
    await expect(student.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
    expect((await loggedOut).status()).toBe(200);
    expect((await request(student, 'GET', '/users/me', changedToken)).status()).toBe(401);
    console.log('通过：界面改密撤销全部设备会话、重新登录与服务端退出失效。');
  }
} finally {
  for (const context of contexts) await context.close();
  await browser.close();
}
