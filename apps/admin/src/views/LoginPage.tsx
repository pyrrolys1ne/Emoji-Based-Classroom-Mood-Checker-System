import { useState, type FormEvent } from 'react';
import { isIntegration } from '../repositories/http';

export function LoginPage({
  login,
}: {
  login: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
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
        <h1>欢迎回到课堂心晴</h1>
        <p>教师与管理员工作空间</p>
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
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label>
          密码
          <input
            required
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error && (
          <p className="login-error" role="alert">
            {error}
          </p>
        )}
        <button className="button" type="submit" disabled={busy}>
          {busy ? '登录中…' : '登录工作空间'}
        </button>
        <small>账号创建与角色授权由团队后端提供；此页面不开放管理员自助提权。</small>
      </form>
    </div>
  );
}
