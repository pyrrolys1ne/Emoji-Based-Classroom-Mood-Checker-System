import { StrictMode } from 'react';
import '@testing-library/jest-dom/vitest';
import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import type { ClassSession, User } from '@mood/contracts';
import { App } from '../App';
import { ClientError, type ClientRepository } from '../models/client';
import { useClassroom } from '../viewmodels/useClassroom';

const user: User = {
  id: 'student-1',
  username: 'student-a',
  email: 'student@example.test',
  role: 'STUDENT',
  status: 'ACTIVE',
};
const session = (): ClassSession => ({
  id: 'session-1',
  courseId: 'course-1',
  courseName: '课堂',
  teacherName: '教师',
  className: '一班',
  room: '教室',
  startsAt: new Date(Date.now() - 3600000).toISOString(),
  endsAt: new Date(Date.now() + 3600000).toISOString(),
  scheduledUserIds: [user.id],
});
function repository(): ClientRepository {
  return {
    mode: 'api',
    login: vi.fn().mockResolvedValue({ token: 'token', user }),
    register: vi.fn(),
    me: vi.fn().mockResolvedValue(user),
    logout: vi.fn().mockResolvedValue(undefined),
    changePassword: vi.fn(),
    sessions: vi.fn().mockResolvedValue([session()]),
    submit: vi.fn(),
    history: vi.fn().mockResolvedValue([]),
    statistics: vi.fn(),
  };
}
async function login(u: ReturnType<typeof userEvent.setup>) {
  await u.type(screen.getByLabelText('用户名'), 'student-a');
  await u.type(screen.getByLabelText('密码', { exact: true }), 'password123');
  await u.click(screen.getByRole('button', { name: '登录' }));
  await screen.findByRole('heading', { name: '课堂反馈' });
  await waitFor(() => expect(screen.getByLabelText('课堂')).toHaveValue('session-1'));
}
afterEach(() => {
  cleanup();
  sessionStorage.clear();
});

it('请求期间重复提交只发一次，失败保留选择且不显示成功', async () => {
  const repo = repository();
  let reject!: (error: Error) => void;
  vi.mocked(repo.submit).mockImplementation(
    () =>
      new Promise((_, r) => {
        reject = r;
      }),
  );
  const u = userEvent.setup();
  render(<App repository={repo} storage={sessionStorage} />);
  await login(u);
  await u.click(screen.getByRole('button', { name: '开心' }));
  await u.dblClick(screen.getByRole('button', { name: '提交反馈' }));
  expect(repo.submit).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: '正在提交…' })).toBeDisabled();
  expect(screen.getByLabelText('课堂')).toBeDisabled();
  expect(screen.getByRole('button', { name: '我的记录' })).toBeDisabled();
  expect(screen.getByRole('button', { name: '账号' })).toBeDisabled();
  await act(async () => reject(new ClientError('服务不可用', 503)));
  expect(await screen.findByRole('alert')).toHaveTextContent('服务不可用');
  expect(screen.getByRole('button', { name: '开心' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.queryByText('反馈已保存。')).not.toBeInTheDocument();
});

it('退出立即清除个人视图，旧历史响应不能恢复数据；注销失败可见', async () => {
  const repo = repository();
  let resolve!: (records: Awaited<ReturnType<ClientRepository['history']>>) => void;
  vi.mocked(repo.history).mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  vi.mocked(repo.logout).mockRejectedValue(new Error('offline'));
  const u = userEvent.setup();
  render(<App repository={repo} storage={sessionStorage} />);
  await login(u);
  await waitFor(() => expect(repo.history).toHaveBeenCalled());
  await u.click(screen.getByRole('button', { name: '退出' }));
  expect(screen.getByRole('heading', { name: '登录' })).toBeVisible();
  await act(async () =>
    resolve([
      {
        id: 'late',
        userId: user.id,
        sessionId: 'session-1',
        emotion: 'HAPPY',
        source: 'MANUAL',
        confidence: null,
        recordedAt: new Date().toISOString(),
      },
    ]),
  );
  expect(screen.queryByRole('heading', { name: '课堂反馈' })).not.toBeInTheDocument();
  expect(await screen.findByText(/服务器注销尚未确认/)).toBeVisible();
  expect(sessionStorage.getItem('mood-client-auth-api')).toBeNull();
});

it('已登录请求返回 401 时清除身份并要求重新登录', async () => {
  const repo = repository();
  vi.mocked(repo.sessions).mockRejectedValue(new ClientError('expired', 401));
  const u = userEvent.setup();
  render(<App repository={repo} storage={sessionStorage} />);
  await u.type(screen.getByLabelText('用户名'), 'student-a');
  await u.type(screen.getByLabelText('密码', { exact: true }), 'password123');
  await u.click(screen.getByRole('button', { name: '登录' }));
  expect(await screen.findByText('登录已过期，请重新登录。')).toBeVisible();
  expect(screen.getByRole('heading', { name: '登录' })).toBeVisible();
  expect(sessionStorage.getItem('mood-client-auth-api')).toBeNull();
});

it.each([0, 200, 502])('改密响应无法确认（状态 %s）时提示核实结果', async (status) => {
  const repo = repository();
  vi.mocked(repo.changePassword).mockRejectedValue(
    new ClientError('无法确认响应', status, status === 200 ? 'INVALID_RESPONSE' : 'NETWORK_ERROR'),
  );
  const u = userEvent.setup();
  render(<App repository={repo} storage={sessionStorage} />);
  await login(u);
  await u.click(screen.getByRole('button', { name: '账号' }));
  await u.type(screen.getByLabelText('当前密码'), 'oldpassword');
  await u.type(screen.getByLabelText('新密码', { exact: true }), 'newpassword');
  await u.type(screen.getByLabelText('确认新密码'), 'newpassword');
  await u.click(screen.getByRole('button', { name: '修改密码' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('密码修改结果尚未确认');
  expect(screen.getByRole('heading', { name: '账号' })).toBeVisible();
});

it.each([
  ['其他学生', { userId: 'other-student', sessionId: 'session-1', source: 'MANUAL' as const }],
  ['其他课堂', { userId: user.id, sessionId: 'other-session', source: 'MANUAL' as const }],
  ['AI记录', { userId: user.id, sessionId: 'session-1', source: 'AI' as const }],
])('学生历史拒绝展示范围外的%s', async (_name, fields) => {
  const repo = repository();
  vi.mocked(repo.history).mockResolvedValue([
    {
      id: 'bad-record',
      emotion: 'HAPPY',
      confidence: null,
      recordedAt: new Date().toISOString(),
      ...fields,
    },
  ]);
  const u = userEvent.setup();
  render(<App repository={repo} storage={sessionStorage} />);
  await login(u);
  expect(await screen.findByRole('alert')).toHaveTextContent('记录范围与当前账号或课堂不符');
  expect(screen.queryByText('手动反馈')).not.toBeInTheDocument();
});

it('提交未完成时状态层拒绝切换课堂', async () => {
  const repo = repository();
  const second = { ...session(), id: 'session-2', courseName: '第二课堂' };
  vi.mocked(repo.sessions).mockResolvedValue([session(), second]);
  let resolve!: () => void;
  vi.mocked(repo.submit).mockImplementation(
    () =>
      new Promise<void>((r) => {
        resolve = r;
      }),
  );
  const expire = () => false;
  const { result } = renderHook(() => useClassroom(repo, { token: 'token', user }, expire));
  await waitFor(() => expect(result.current.selectedSessionId).toBe('session-1'));
  act(() => result.current.selectEmotion('HAPPY'));
  act(() => {
    void result.current.submit();
  });
  expect(result.current.submitting).toBe(true);
  act(() => result.current.selectSession('session-2'));
  expect(result.current.selectedSessionId).toBe('session-1');
  await act(async () => resolve());
});

it('StrictMode 下恢复缓存身份并重新向仓储核验', async () => {
  const repo = repository();
  sessionStorage.setItem('mood-client-auth-api', JSON.stringify({ token: 'token', user }));
  render(
    <StrictMode>
      <App repository={repo} storage={sessionStorage} />
    </StrictMode>,
  );
  expect(await screen.findByRole('heading', { name: '课堂反馈' })).toBeVisible();
  expect(repo.me).toHaveBeenCalledWith('token', expect.any(AbortSignal));
  expect(screen.getByText('student-a')).toBeVisible();
});
