import { useEffect, useState, type FormEvent } from 'react';
import { emotions, type Emotion, type EmojiRecord, type ClassSession } from '@mood/contracts';
import type {
  AccountViewProps,
  AppShellProps,
  AuthViewProps,
  HistoryViewProps,
  StudentViewProps,
  TeacherViewProps,
} from '../models/client';

const choices = Object.entries(emotions) as [Emotion, (typeof emotions)[Emotion]][];
const dateTime = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });
};
const roleName = (role: string) =>
  role === 'STUDENT' ? '学生' : role === 'TEACHER' ? '教师' : '管理员';

function Feedback({ error, notice }: { error?: string; notice?: string }) {
  return (
    <>
      {error && (
        <p className="message error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="message notice" role="status">
          {notice}
        </p>
      )}
    </>
  );
}
function RetryError({ error, retry }: { error: string; retry: () => void }) {
  return (
    <div className="message error" role="alert">
      {error}{' '}
      <button type="button" className="text-button" onClick={retry}>
        重试
      </button>
    </div>
  );
}
function SessionSelect({
  sessions,
  value,
  onChange,
  all = false,
  disabled = false,
}: {
  sessions: ClassSession[];
  value: string;
  onChange: (value: string) => void;
  all?: boolean;
  disabled?: boolean;
}) {
  return (
    <div className="field session-select">
      <label htmlFor="session-select">课堂</label>
      <select
        id="session-select"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      >
        {all ? <option value="">全部课堂</option> : <option value="">请选择课堂</option>}
        {sessions.map((session) => (
          <option key={session.id} value={session.id}>
            {session.courseName} · {session.className} · {dateTime(session.startsAt)}
          </option>
        ))}
      </select>
    </div>
  );
}
function Records({
  records,
  sessions,
  showStudent = false,
}: {
  records: EmojiRecord[];
  sessions: ClassSession[];
  showStudent?: boolean;
}) {
  return (
    <ul className="record-list">
      {records.map((record) => {
        const session = sessions.find((item) => item.id === record.sessionId);
        const emotion = emotions[record.emotion];
        return (
          <li key={record.id} className="record">
            <span className="record-emoji" aria-hidden="true">
              {emotion.emoji}
            </span>
            <div className="record-main">
              <strong>{emotion.label}</strong>
              <span>{session ? `${session.courseName} · ${session.className}` : '课堂记录'}</span>
              {showStudent && (
                <span>
                  {record.source === 'AI'
                    ? 'AI 匿名'
                    : record.userId
                      ? `学生 · ${record.userId.slice(0, 8)}`
                      : '匿名记录'}
                </span>
              )}
            </div>
            <div className="record-meta">
              <time dateTime={record.recordedAt}>{dateTime(record.recordedAt)}</time>
              <span>
                {record.source === 'AI' ? 'AI 记录' : '手动反馈'}
                {record.simulated ? '（模拟）' : ''}
              </span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function AuthView({
  view,
  onViewChange,
  onLogin,
  onRegister,
  pending,
  error,
  notice,
  mode,
  initialUsername,
}: AuthViewProps) {
  const [username, setUsername] = useState(initialUsername);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [role, setRole] = useState<'STUDENT' | 'TEACHER'>('STUDENT');
  const [localError, setLocalError] = useState('');
  useEffect(() => setUsername(initialUsername), [initialUsername]);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (view === 'register' && password !== confirm) {
      setLocalError('两次输入的密码不一致。');
      return;
    }
    setLocalError('');
    const ok =
      view === 'login'
        ? await onLogin({ username: username.trim(), password })
        : await onRegister({ username: username.trim(), email: email.trim(), password, role });
    if (ok) {
      setPassword('');
      setConfirm('');
    }
  };
  const demoLogin = async (name: string) => {
    setLocalError('');
    if (await onLogin({ username: name, password: 'classroom-demo-2026' })) {
      setPassword('');
      setConfirm('');
    }
  };
  return (
    <main id="main-content" className="auth-page">
      <div className="auth-brand">
        课堂心晴 <span>课堂情绪反馈</span>
      </div>
      <section className="auth-panel" aria-busy={pending}>
        <h1>{view === 'login' ? '登录' : '创建账号'}</h1>
        <p className="intro">
          {view === 'login' ? '登录后选择课堂，记录你的感受。' : '填写信息，开始使用课堂心晴。'}
        </p>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="username">用户名</label>
            <input
              id="username"
              autoComplete="username"
              required
              minLength={2}
              maxLength={50}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          {view === 'register' && (
            <div className="field">
              <label htmlFor="email">邮箱</label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          )}
          <div className="field">
            <label htmlFor="password">密码</label>
            <input
              id="password"
              type="password"
              autoComplete={view === 'login' ? 'current-password' : 'new-password'}
              required
              minLength={8}
              maxLength={128}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {view === 'register' && (
            <>
              <div className="field">
                <label htmlFor="confirm-password">确认密码</label>
                <input
                  id="confirm-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={8}
                  maxLength={128}
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="role">申请身份</label>
                <select
                  id="role"
                  value={role}
                  onChange={(e) => setRole(e.target.value as 'STUDENT' | 'TEACHER')}
                >
                  <option value="STUDENT">学生</option>
                  <option value="TEACHER">教师申请</option>
                </select>
                <small>教师身份由后台审核和决定。</small>
              </div>
            </>
          )}
          <Feedback error={localError || error} notice={notice} />
          <button className="primary full" type="submit" disabled={pending}>
            {pending ? '请稍候…' : view === 'login' ? '登录' : '注册'}
          </button>
        </form>
        <p className="auth-switch">
          {view === 'login' ? '还没有账号？' : '已有账号？'}{' '}
          <button
            className="text-button"
            type="button"
            disabled={pending}
            onClick={() => {
              setLocalError('');
              onViewChange(view === 'login' ? 'register' : 'login');
            }}
          >
            {view === 'login' ? '注册' : '去登录'}
          </button>
        </p>
        {mode === 'demo' && (
          <div className="demo-actions">
            <p>演示模式</p>
            <button type="button" disabled={pending} onClick={() => void demoLogin('student-a')}>
              体验学生端
            </button>
            <button type="button" disabled={pending} onClick={() => void demoLogin('teacher-a')}>
              体验教师端
            </button>
          </div>
        )}
      </section>
    </main>
  );
}

export function AppShell({
  user,
  mode,
  page,
  onNavigate,
  onLogout,
  logoutPending,
  navigationPending = false,
  notice,
  adminUrl,
  children,
}: AppShellProps) {
  const links =
    user.role === 'STUDENT'
      ? [
          { id: 'feedback' as const, label: '课堂反馈' },
          { id: 'history' as const, label: '我的记录' },
          { id: 'account' as const, label: '账号' },
        ]
      : [
          { id: 'teacher' as const, label: '课堂记录' },
          { id: 'account' as const, label: '账号' },
        ];
  return (
    <>
      <a className="skip-link" href="#main-content">
        跳转到主要内容
      </a>
      <header className="site-header">
        <div className="header-inner">
          <div className="brand">
            课堂心晴 {mode === 'demo' && <span className="demo-badge">演示模式</span>}
          </div>
          <div className="user-actions">
            <span className="identity">
              {roleName(user.role)} <strong>{user.username}</strong>
            </span>
            {user.role === 'TEACHER' && adminUrl && (
              <a href={adminUrl} target="_blank" rel="noopener noreferrer">
                管理端
              </a>
            )}
            <button
              type="button"
              className="text-button"
              onClick={onLogout}
              disabled={logoutPending}
            >
              {logoutPending ? '正在退出…' : '退出'}
            </button>
          </div>
        </div>
        <nav className="nav-inner" aria-label="主导航">
          {links.map((link) => (
            <button
              type="button"
              key={link.id}
              className={page === link.id ? 'active' : ''}
              aria-current={page === link.id ? 'page' : undefined}
              disabled={navigationPending}
              onClick={() => onNavigate(link.id)}
            >
              {link.label}
            </button>
          ))}
        </nav>
      </header>
      <main id="main-content" className="content">
        <Feedback notice={notice} />
        {children}
      </main>
    </>
  );
}

export function StudentView(props: StudentViewProps) {
  const selected = props.sessions.find((session) => session.id === props.selectedSessionId);
  return (
    <div className="page">
      <header className="page-heading">
        <h1>课堂反馈</h1>
        <p>选择课堂和此刻的感受，提交一条反馈。</p>
      </header>
      <section
        className="section"
        aria-labelledby="class-heading"
        aria-busy={props.sessionsLoading}
      >
        <h2 id="class-heading">选择课堂</h2>
        {props.sessionsLoading ? (
          <p role="status">正在加载课堂…</p>
        ) : props.sessionsError ? (
          <RetryError error={props.sessionsError} retry={props.onSessionsRetry} />
        ) : props.sessions.length === 0 ? (
          <p className="empty">暂无课堂，请联系老师安排课堂。</p>
        ) : (
          <>
            <SessionSelect
              sessions={props.sessions}
              value={props.selectedSessionId}
              onChange={props.onSessionChange}
              disabled={props.submitting}
            />
            {selected && (
              <div className="session-details">
                <strong>{selected.courseName}</strong>
                <span>
                  {selected.className}　{selected.room}
                </span>
                <span>
                  {dateTime(selected.startsAt)} 至 {dateTime(selected.endsAt)}
                </span>
                <span>
                  {props.canSubmit ? '课堂进行中，可以提交反馈' : '当前课堂不在可提交时间内'}
                </span>
              </div>
            )}
          </>
        )}
      </section>
      <section className="section" aria-labelledby="emotion-heading">
        <h2 id="emotion-heading">选择你的感受</h2>
        <div className="emotion-grid" role="group" aria-label="选择一种感受">
          {choices.map(([key, value]) => (
            <button
              type="button"
              key={key}
              aria-pressed={props.selectedEmotion === key}
              className="emotion"
              onClick={() => props.onEmotionChange(key)}
              disabled={props.submitting}
            >
              <span aria-hidden="true">{value.emoji}</span>
              {value.label}
            </button>
          ))}
        </div>
        <Feedback error={props.submitError} notice={props.submitNotice} />
        <button
          className="primary submit-button"
          type="button"
          onClick={props.onSubmit}
          disabled={
            !props.canSubmit ||
            !selected ||
            !props.selectedEmotion ||
            props.submitting ||
            props.sessionsLoading ||
            Boolean(props.sessionsError)
          }
          aria-busy={props.submitting}
        >
          {props.submitting ? '正在提交…' : '提交反馈'}
        </button>
      </section>
      <section
        className="section"
        aria-labelledby="recent-heading"
        aria-busy={props.historyLoading}
      >
        <h2 id="recent-heading">最近的反馈</h2>
        {props.historyLoading ? (
          <p role="status">正在加载记录…</p>
        ) : props.historyError ? (
          <RetryError error={props.historyError} retry={props.onHistoryRetry} />
        ) : props.records.length ? (
          <Records
            records={[...props.records]
              .sort((a, b) => Date.parse(b.recordedAt) - Date.parse(a.recordedAt))
              .slice(0, 5)}
            sessions={props.sessions}
          />
        ) : (
          <p className="empty">还没有反馈记录。</p>
        )}
      </section>
    </div>
  );
}

export function HistoryView(props: HistoryViewProps) {
  return (
    <div className="page">
      <header className="page-heading">
        <h1>我的记录</h1>
        <p>查看自己提交的课堂反馈。</p>
      </header>
      <section className="section" aria-busy={props.loading}>
        <SessionSelect
          sessions={props.sessions}
          value={props.selectedSessionId}
          onChange={props.onSessionChange}
          all
        />
        {props.loading ? (
          <p role="status">正在加载记录…</p>
        ) : props.error ? (
          <RetryError error={props.error} retry={props.onRetry} />
        ) : props.records.length ? (
          <Records records={props.records} sessions={props.sessions} />
        ) : (
          <p className="empty">所选范围暂无反馈记录。</p>
        )}
      </section>
    </div>
  );
}

export function TeacherView(props: TeacherViewProps) {
  const [student, setStudent] = useState('');
  useEffect(() => setStudent(''), [props.selectedSessionId]);
  const ids = Array.from(
    new Set(
      props.records
        .filter((record) => record.source !== 'AI' && record.userId)
        .map((record) => record.userId as string),
    ),
  );
  const filtered =
    student === 'ai'
      ? props.records.filter((record) => record.source === 'AI')
      : student
        ? props.records.filter((record) => record.userId === student && record.source !== 'AI')
        : props.records;
  const selected = props.sessions.find((session) => session.id === props.selectedSessionId);
  return (
    <div className="page">
      <header className="page-heading">
        <h1>课堂记录</h1>
        <p>查看所授课堂的反馈和整体分布。</p>
      </header>
      <section className="section">
        <SessionSelect
          sessions={props.sessions}
          value={props.selectedSessionId}
          onChange={props.onSessionChange}
        />
        {props.loading && !props.selectedSessionId ? (
          <p role="status">正在加载课堂…</p>
        ) : props.error && !props.selectedSessionId ? (
          <RetryError error={props.error} retry={props.onRetry} />
        ) : (
          props.sessions.length === 0 && <p className="empty">暂无可查看的课堂。</p>
        )}
        {selected && (
          <p className="muted">
            {selected.className}　{dateTime(selected.startsAt)} 至 {dateTime(selected.endsAt)}
          </p>
        )}
      </section>
      {props.selectedSessionId && (
        <>
          <section
            className="section"
            aria-labelledby="stats-heading"
            aria-busy={props.statisticsLoading}
          >
            <h2 id="stats-heading">课堂整体分布</h2>
            {props.statisticsLoading ? (
              <p role="status">正在加载统计…</p>
            ) : props.statisticsError ? (
              <div className="message error" role="alert">
                {props.statisticsError}{' '}
                <button type="button" className="text-button" onClick={props.onRetry}>
                  重试
                </button>
              </div>
            ) : props.statistics ? (
              <>
                <p className="muted">共 {props.statistics.total} 条记录</p>
                <ul className="distribution">
                  {choices.map(([key, value]) => {
                    const count = props.statistics!.distribution[key];
                    const percent =
                      props.statistics!.total > 0
                        ? Math.max(0, Math.min(100, (count / props.statistics!.total) * 100))
                        : 0;
                    return (
                      <li key={key}>
                        <span>
                          {value.emoji} {value.label}
                        </span>
                        <span className="bar" aria-hidden="true">
                          <span style={{ width: `${percent}%` }} />
                        </span>
                        <strong>{count}</strong>
                      </li>
                    );
                  })}
                </ul>
              </>
            ) : (
              <p className="empty">暂无课堂整体统计。</p>
            )}
          </section>
          <section className="section" aria-labelledby="records-heading" aria-busy={props.loading}>
            <h2 id="records-heading">课堂历史</h2>
            <div className="field session-select">
              <label htmlFor="student-filter">筛选记录</label>
              <select
                id="student-filter"
                value={student}
                onChange={(event) => setStudent(event.target.value)}
              >
                <option value="">全部记录</option>
                {ids.map((id) => (
                  <option key={id} value={id}>
                    学生 · {id.slice(0, 8)}
                  </option>
                ))}
                {props.records.some((record) => record.source === 'AI') && (
                  <option value="ai">AI 匿名</option>
                )}
              </select>
            </div>
            {props.loading ? (
              <p role="status">正在加载记录…</p>
            ) : props.error ? (
              <RetryError error={props.error} retry={props.onRetry} />
            ) : filtered.length ? (
              <Records records={filtered} sessions={props.sessions} showStudent />
            ) : (
              <p className="empty">所选范围暂无记录。</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}

export function AccountView({ user, onChangePassword, pending, error, notice }: AccountViewProps) {
  const [oldPassword, setOld] = useState('');
  const [newPassword, setNew] = useState('');
  const [confirm, setConfirm] = useState('');
  const [localError, setLocalError] = useState('');
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (newPassword !== confirm) {
      setLocalError('两次输入的新密码不一致。');
      return;
    }
    setLocalError('');
    if (await onChangePassword({ oldPassword, newPassword })) {
      setOld('');
      setNew('');
      setConfirm('');
    }
  };
  return (
    <div className="page">
      <header className="page-heading">
        <h1>账号</h1>
        <p>查看个人信息和修改密码。</p>
      </header>
      <section className="section">
        <h2>个人信息</h2>
        <dl className="account-info">
          <div>
            <dt>用户名</dt>
            <dd>{user.username}</dd>
          </div>
          <div>
            <dt>邮箱</dt>
            <dd>{user.email}</dd>
          </div>
          <div>
            <dt>身份</dt>
            <dd>{roleName(user.role)}</dd>
          </div>
        </dl>
      </section>
      <section className="section">
        <h2>修改密码</h2>
        <p className="muted">密码修改成功后需重新登录。</p>
        <form className="password-form" onSubmit={submit} aria-busy={pending}>
          <div className="field">
            <label htmlFor="old-password">当前密码</label>
            <input
              id="old-password"
              type="password"
              autoComplete="current-password"
              required
              value={oldPassword}
              onChange={(e) => setOld(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="new-password">新密码</label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              maxLength={128}
              value={newPassword}
              onChange={(e) => setNew(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="confirm-new-password">确认新密码</label>
            <input
              id="confirm-new-password"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              maxLength={128}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>
          <Feedback error={localError || error} notice={notice} />
          <button type="submit" className="primary" disabled={pending}>
            {pending ? '正在修改…' : '修改密码'}
          </button>
        </form>
      </section>
    </div>
  );
}
