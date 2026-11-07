import { useState, type FormEvent } from 'react';
import { isIntegration } from '../repositories/http';
import { adminRegistrationEnabled } from '../repositories/adminRegistrationRepository';
import { useAdminRegistration } from '../controllers/useAdminRegistration';

export function LoginPage({
  login,
}: {
  login: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [email, setEmail] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [invitationCode, setInvitationCode] = useState('');
  const [notice, setNotice] = useState('');
  const registration = useAdminRegistration();
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || registration.busy) return;
    setError('');
    setNotice('');
    if (registering) {
      if (password !== confirmation) {
        setError('两次输入的密码不一致。');
        return;
      }
      if (
        await registration.register({
          username: username.trim(),
          email: email.trim(),
          password,
          invitationCode: invitationCode.trim(),
        })
      ) {
        setRegistering(false);
        setPassword('');
        setConfirmation('');
        setInvitationCode('');
        setNotice('管理员注册成功，请登录。');
      }
      return;
    }
    setBusy(true);
    setError('');
    try {
      await login(username, password);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败');
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="login-shell">
      <form className="login-card" onSubmit={(event) => void submit(event)}>
        <div className="eyebrow">CLASSROOM MOOD</div>
        <h1>{registering ? '管理员注册' : '欢迎回到课堂心晴'}</h1>
        <p>{registering ? '使用有效的一次性邀请码创建管理员账号' : '教师与管理员工作空间'}</p>
        {notice && <p role="status">{notice}</p>}
        {isIntegration && (
          <div className="notice">
            本地联调专用合成账号：admin 或 teacher，密码均为
            integration-only。此环境不连接真实用户数据。
          </div>
        )}
        <label>
          用户名
          <input
            required
            minLength={registering ? 2 : undefined}
            maxLength={50}
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        {registering && (
          <label>
            邮箱
            <input
              required
              type="email"
              autoComplete="email"
              maxLength={254}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
        )}
        <label>
          密码
          <input
            required
            type="password"
            minLength={registering ? 8 : undefined}
            maxLength={128}
            autoComplete={registering ? 'new-password' : 'current-password'}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {registering && (
          <>
            <label>
              确认密码
              <input
                required
                type="password"
                autoComplete="new-password"
                minLength={8}
                maxLength={128}
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
              />
            </label>
            <label>
              邀请码
              <input
                required
                autoComplete="off"
                maxLength={47}
                value={invitationCode}
                onChange={(event) => setInvitationCode(event.target.value)}
              />
            </label>
          </>
        )}
        {(error || (registering && registration.error)) && (
          <p className="login-error" role="alert">
            {error || registration.error}
          </p>
        )}
        <button className="button" type="submit" disabled={busy || registration.busy}>
          {registering
            ? registration.busy
              ? '注册中…'
              : '注册管理员'
            : busy
              ? '登录中…'
              : '登录工作空间'}
        </button>
        {adminRegistrationEnabled && (
          <button
            className="text-button"
            type="button"
            disabled={busy || registration.busy}
            onClick={() => {
              setRegistering(!registering);
              registration.reset();
              setError('');
              setNotice('');
              setPassword('');
              setConfirmation('');
              setInvitationCode('');
            }}
          >
            {registering ? '返回登录' : '管理员注册'}
          </button>
        )}
        <small>教师和学生在客户端注册；管理员注册需持有有效邀请码。</small>
      </form>
    </div>
  );
}
