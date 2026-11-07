// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
const requests = vi.hoisted(() => ({ register: vi.fn(), invite: vi.fn() }));
vi.mock('../repositories/adminRegistrationRepository', () => ({
  adminRegistrationEnabled: true,
  adminRegistrationRepository: requests,
}));
import { LoginPage } from './LoginPage';
import { AdminInvitationPanel } from './components/AdminInvitationPanel';

const code = 'adm_' + 'x'.repeat(43);
beforeEach(() => {
  requests.register.mockReset();
  requests.invite.mockReset();
});
afterEach(cleanup);

function form(login = vi.fn()) {
  render(<LoginPage login={login} />);
  fireEvent.click(screen.getByRole('button', { name: '管理员注册' }));
  for (const [label, value] of [
    ['用户名', 'new-admin'],
    ['邮箱', 'new-admin@example.edu'],
    ['密码', 'synthetic-password'],
    ['确认密码', 'synthetic-password'],
    ['邀请码', code],
  ])
    fireEvent.change(screen.getByLabelText(label, { exact: true }), { target: { value } });
  return screen.getByRole('button', { name: '注册管理员' }).closest('form')!;
}

it('registers with an invitation and clears secrets before returning to login', async () => {
  requests.register.mockResolvedValue(undefined);
  const login = vi.fn();
  fireEvent.submit(form(login));
  await screen.findByText('管理员注册成功，请登录。');
  expect(requests.register).toHaveBeenCalledWith({
    username: 'new-admin',
    email: 'new-admin@example.edu',
    password: 'synthetic-password',
    invitationCode: code,
  });
  expect((screen.getByLabelText('密码', { exact: true }) as HTMLInputElement).value).toBe('');
  expect(screen.queryByLabelText('邀请码')).toBeNull();
  expect(login).not.toHaveBeenCalled();
});

it('rejects mismatched confirmation before sending any registration', () => {
  const target = form();
  fireEvent.change(screen.getByLabelText('确认密码'), { target: { value: 'different-password' } });
  fireEvent.submit(target);
  expect(screen.getByRole('alert').textContent).toContain('两次输入的密码不一致');
  expect(requests.register).not.toHaveBeenCalled();
});

it('sends only one registration while an invitation redemption is pending', async () => {
  let complete!: () => void;
  requests.register.mockImplementation(
    () =>
      new Promise<void>((resolve) => {
        complete = resolve;
      }),
  );
  const target = form();
  fireEvent.submit(target);
  fireEvent.submit(target);
  expect(requests.register).toHaveBeenCalledTimes(1);
  expect((screen.getByRole('button', { name: '注册中…' }) as HTMLButtonElement).disabled).toBe(
    true,
  );
  complete();
  await screen.findByText('管理员注册成功，请登录。');
});

it('preserves the form and reports a rejected invitation without successful registration', async () => {
  requests.register.mockRejectedValue(new Error('邀请码无效、已使用或已过期'));
  fireEvent.submit(form());
  expect((await screen.findByRole('alert')).textContent).toContain('已过期');
  expect(screen.queryByText('管理员注册成功，请登录。')).toBeNull();
  expect((screen.getByLabelText('邮箱') as HTMLInputElement).value).toBe('new-admin@example.edu');
  fireEvent.click(screen.getByRole('button', { name: '返回登录' }));
  fireEvent.click(screen.getByRole('button', { name: '管理员注册' }));
  expect(screen.queryByRole('alert')).toBeNull();
});

it('shows a server-issued invitation and allows hiding the credential', async () => {
  requests.invite.mockResolvedValue({ code, expiresAt: '2030-01-01T00:00:00Z' });
  render(<AdminInvitationPanel />);
  fireEvent.click(screen.getByRole('button', { name: '生成管理员邀请码' }));
  await screen.findByRole('status');
  expect(requests.invite).toHaveBeenCalledWith(24);
  expect((screen.getByLabelText('一次性邀请码') as HTMLInputElement).value).toBe(code);
  fireEvent.click(screen.getByRole('button', { name: '隐藏邀请码' }));
  expect(screen.queryByLabelText('一次性邀请码')).toBeNull();
});

it('does not display a successful invitation when the server rejects issuance', async () => {
  requests.invite.mockRejectedValue(new Error('该操作仅限管理员'));
  render(<AdminInvitationPanel />);
  fireEvent.click(screen.getByRole('button', { name: '生成管理员邀请码' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('仅限管理员'));
  expect(screen.queryByLabelText('一次性邀请码')).toBeNull();
});
