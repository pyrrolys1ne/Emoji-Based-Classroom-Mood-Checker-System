import { useEffect, useState, type ReactNode } from 'react';
import {
  ArrowDownToLine,
  ArrowRight,
  BarChart3,
  CalendarDays,
  ChevronDown,
  CircleHelp,
  LayoutDashboard,
  Menu,
  MessageCircle,
  RefreshCw,
  Smile,
  Users,
  X,
} from 'lucide-react';
import { emotions, type ClassSession, type EmojiRecord, type WorkspaceData } from '@mood/contracts';
import { useWorkspace } from '../controllers/useWorkspace';
import { distribution, exportRecords, sessionRecords } from '../models/workspace';
import { isDemo } from '../repositories/workspaceRepository';

const pages = [
  { id: 'dashboard', label: '课堂概览', icon: LayoutDashboard },
  { id: 'users', label: '用户管理', icon: Users },
  { id: 'records', label: '情绪记录', icon: MessageCircle },
  { id: 'sessions', label: '课堂安排', icon: CalendarDays },
  { id: 'statistics', label: '多维统计', icon: BarChart3 },
] as const;
type Page = (typeof pages)[number]['id'];
const time = (value: string) =>
  new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
const roleNames = { STUDENT: '学生', TEACHER: '教师', ADMIN: '管理员' };
const readPage = (): Page =>
  pages.find((page) => page.id === location.hash.slice(1))?.id ?? 'dashboard';

function Panel({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Empty() {
  return <div className="empty">暂无符合条件的数据</div>;
}

function EmotionChart({ records }: { records: EmojiRecord[] }) {
  const items = distribution(records);
  return (
    <div className="emotion-chart">
      {items.map((item) => (
        <div className="emotion-row" key={item.key}>
          <span className="emotion-name">
            {item.emoji} {item.label}
          </span>
          <div className="bar-track">
            <span
              style={{
                width: `${records.length ? (item.count / records.length) * 100 : 0}%`,
                background: item.color,
              }}
            />
          </div>
          <strong>{item.count}</strong>
          <span className="muted">
            {records.length ? Math.round((item.count / records.length) * 100) : 0}%
          </span>
        </div>
      ))}
    </div>
  );
}

function Trend({ records }: { records: EmojiRecord[] }) {
  const counts = Array.from(
    { length: 6 },
    (_, index) =>
      records.filter(
        (record) => Math.floor(new Date(record.recordedAt).getMinutes() / 10) === index,
      ).length,
  );
  const max = Math.max(1, ...counts);
  const points = counts
    .map((count, index) => `${40 + index * 92},${145 - (count / max) * 108}`)
    .join(' ');
  return (
    <div className="trend">
      <svg viewBox="0 0 540 190" role="img" aria-label="按每小时内十分钟区间汇总的记录数量">
        <defs>
          <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b9c7a" stopOpacity=".22" />
            <stop offset="100%" stopColor="#3b9c7a" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 1, 2].map((index) => (
          <line
            key={index}
            x1="40"
            x2="500"
            y1={37 + index * 54}
            y2={37 + index * 54}
            stroke="#e8eeeb"
            strokeDasharray="4 5"
          />
        ))}
        <polygon points={`40,150 ${points} 500,150`} fill="url(#area)" />
        <polyline
          points={points}
          fill="none"
          stroke="#329374"
          strokeWidth="3"
          strokeLinejoin="round"
        />
        {counts.map((count, index) => (
          <g key={index}>
            <circle cx={40 + index * 92} cy={145 - (count / max) * 108} r="4" fill="#329374" />
            <text x={40 + index * 92} y="178" textAnchor="middle">
              {index * 10}–{index * 10 + 9}分
            </text>
          </g>
        ))}
      </svg>
      <p className="chart-note">按记录时间的分钟数聚合 · 当前筛选范围</p>
    </div>
  );
}

function RecordTable({ data, records }: { data: WorkspaceData; records: EmojiRecord[] }) {
  if (!records.length) return <Empty />;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>情绪</th>
            <th>用户</th>
            <th>课程 / 班级</th>
            <th>来源</th>
            <th>置信度</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => {
            const session = data.sessions.find((item) => item.id === record.sessionId);
            return (
              <tr key={record.id}>
                <td>
                  <span className="emotion-pill">
                    {emotions[record.emotion].emoji} {emotions[record.emotion].label}
                  </span>
                </td>
                <td>{data.users.find((user) => user.id === record.userId)?.username ?? '匿名'}</td>
                <td>
                  {session?.courseName}
                  <small>{session?.className}</small>
                </td>
                <td>
                  <span className={`tag ${record.source === 'AI' ? 'purple' : ''}`}>
                    {record.source === 'AI' ? 'AI 识别' : '手动提交'}
                  </span>
                </td>
                <td>
                  {record.confidence === null ? '—' : `${Math.round(record.confidence * 100)}%`}
                </td>
                <td>{time(record.recordedAt)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Dashboard({
  data,
  records,
  go,
}: {
  data: WorkspaceData;
  records: EmojiRecord[];
  go: (page: Page) => void;
}) {
  const manualUsers = new Set(
    records.filter((record) => record.userId).map((record) => record.userId),
  ).size;
  const aiCount = records.filter((record) => record.source === 'AI').length;
  return (
    <>
      <div className="welcome">
        <div>
          <span className="eyebrow">每一种感受，都值得被看见</span>
          <h2>从一个表情，读懂课堂。</h2>
          <p>关注学生的当下感受，让教学反馈更及时。</p>
          <button className="welcome-link" onClick={() => go('sessions')}>
            查看课堂安排 <ArrowRight size={16} />
          </button>
        </div>
        <div className="emoji-orbit" aria-hidden="true">
          <span>😊</span>
          <span>🤓</span>
          <span>🤔</span>
          <div className="orbit-caption">CLASSROOM MOOD</div>
        </div>
      </div>
      <div className="metrics">
        {[
          ['情绪记录', records.length, '当前课堂筛选范围', MessageCircle],
          ['参与学生', manualUsers, '按手动提交用户去重', Users],
          ['课堂会话', data.sessions.length, '已安排的课堂数量', CalendarDays],
          [
            'AI 采集占比',
            `${records.length ? Math.round((aiCount / records.length) * 100) : 0}%`,
            `${aiCount} 条匿名识别记录`,
            Smile,
          ],
        ].map(([label, value, hint, Icon]) => {
          const MetricIcon = Icon as typeof Smile;
          return (
            <div className="metric" key={String(label)}>
              <div className="metric-top">
                <span>{String(label)}</span>
                <MetricIcon size={18} />
              </div>
              <strong>{String(value)}</strong>
              <small>{String(hint)}</small>
            </div>
          );
        })}
      </div>
      <div className="two-columns">
        <Panel title="课堂情绪分布" description="了解当前课堂的整体感受">
          <EmotionChart records={records} />
        </Panel>
        <Panel title="反馈时间分布" description="每十分钟内的情绪记录数量">
          <Trend records={records} />
        </Panel>
      </div>
      <Panel
        title="最近情绪记录"
        description="手动反馈与 AI 识别统一展示"
        action={
          <button className="text-button" onClick={() => go('records')}>
            查看全部 <ArrowRight size={15} />
          </button>
        }
      >
        <RecordTable
          data={data}
          records={[...records]
            .sort((a, b) => b.recordedAt.localeCompare(a.recordedAt))
            .slice(0, 5)}
        />
      </Panel>
    </>
  );
}

function UsersPage({ data }: { data: WorkspaceData }) {
  const [query, setQuery] = useState('');
  const [role, setRole] = useState('');
  const users = data.users.filter(
    (user) =>
      (!role || user.role === role) &&
      `${user.username} ${user.email}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <Panel
      title="用户目录"
      description={`共 ${data.users.length} 位用户，当前显示 ${users.length} 位`}
    >
      <div className="filters">
        <input
          aria-label="搜索用户"
          placeholder="搜索姓名或邮箱…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <select
          aria-label="筛选角色"
          value={role}
          onChange={(event) => setRole(event.target.value)}
        >
          <option value="">全部角色</option>
          {Object.entries(roleNames).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {users.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>用户</th>
                <th>邮箱</th>
                <th>角色</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>
                    <span className="user-avatar">{user.username[0]}</span>
                    {user.username}
                  </td>
                  <td>{user.email}</td>
                  <td>{roleNames[user.role]}</td>
                  <td>
                    <span className="tag">{user.status === 'ACTIVE' ? '正常' : '已停用'}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty />
      )}
    </Panel>
  );
}

function RecordsPage({ data, records }: { data: WorkspaceData; records: EmojiRecord[] }) {
  const [source, setSource] = useState('');
  const [emotion, setEmotion] = useState('');
  const [page, setPage] = useState(1);
  const filtered = records
    .filter(
      (record) => (!source || record.source === source) && (!emotion || record.emotion === emotion),
    )
    .sort((a, b) => b.recordedAt.localeCompare(a.recordedAt));
  const totalPages = Math.max(1, Math.ceil(filtered.length / 10));
  const current = Math.min(page, totalPages);
  return (
    <Panel
      title="情绪记录"
      description="按情绪类型和采集来源查找课堂反馈"
      action={
        <button className="button" onClick={() => exportRecords(data, filtered)}>
          <ArrowDownToLine size={16} />
          导出 CSV
        </button>
      }
    >
      <div className="filters">
        <select
          aria-label="筛选来源"
          value={source}
          onChange={(event) => {
            setSource(event.target.value);
            setPage(1);
          }}
        >
          <option value="">全部来源</option>
          <option value="MANUAL">手动提交</option>
          <option value="AI">AI 识别</option>
        </select>
        <select
          aria-label="筛选情绪"
          value={emotion}
          onChange={(event) => {
            setEmotion(event.target.value);
            setPage(1);
          }}
        >
          <option value="">全部情绪</option>
          {Object.entries(emotions).map(([key, value]) => (
            <option key={key} value={key}>
              {value.emoji} {value.label}
            </option>
          ))}
        </select>
        <span className="muted">{filtered.length} 条记录</span>
      </div>
      <RecordTable data={data} records={filtered.slice((current - 1) * 10, current * 10)} />
      <div className="pagination">
        <span>
          第 {current} / {totalPages} 页
        </span>
        <button
          className="button secondary"
          disabled={current === 1}
          onClick={() => setPage(current - 1)}
        >
          上一页
        </button>
        <button
          className="button secondary"
          disabled={current === totalPages}
          onClick={() => setPage(current + 1)}
        >
          下一页
        </button>
      </div>
    </Panel>
  );
}

function ScheduleDialog({
  session,
  data,
  save,
  close,
}: {
  session: ClassSession;
  data: WorkspaceData;
  save: (sessionId: string, userIds: string[]) => Promise<void>;
  close: () => void;
}) {
  const [selected, setSelected] = useState(session.scheduledUserIds);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const students = data.users.filter((user) => user.role === 'STUDENT');
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLDialogElement>('dialog');
    dialog?.showModal();
    return () => {
      dialog?.close();
      previous?.focus();
    };
  }, []);
  const submit = async () => {
    setSaving(true);
    try {
      await save(session.id, selected);
      close();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };
  return (
    <dialog
      onCancel={(event) => {
        event.preventDefault();
        if (!saving) close();
      }}
      aria-labelledby="schedule-title"
    >
      <div className="dialog-header">
        <div>
          <h2 id="schedule-title">安排课堂学生</h2>
          <p>
            {session.courseName} · {session.className}
          </p>
        </div>
        <button className="icon-button" aria-label="关闭" disabled={saving} onClick={close}>
          <X size={20} />
        </button>
      </div>
      <div className="student-list">
        {students.map((user) => (
          <label key={user.id}>
            <input
              type="checkbox"
              checked={selected.includes(user.id)}
              onChange={(event) =>
                setSelected((current) =>
                  event.target.checked
                    ? [...current, user.id]
                    : current.filter((id) => id !== user.id),
                )
              }
            />
            <span>{user.username}</span>
            <small>{user.email}</small>
          </label>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      <div className="dialog-footer">
        <span>已选 {selected.length} 人</span>
        <button className="button" disabled={saving} onClick={() => void submit()}>
          {saving ? '保存中…' : '保存安排'}
        </button>
      </div>
    </dialog>
  );
}

function SessionsPage({
  data,
  save,
}: {
  data: WorkspaceData;
  save: (sessionId: string, userIds: string[]) => Promise<void>;
}) {
  const [editing, setEditing] = useState<ClassSession | null>(null);
  return (
    <>
      <Panel title="课堂与学生安排" description="按课堂会话管理上课时间和参与学生">
        <div className="session-grid">
          {data.sessions.map((session) => (
            <article className="session-card" key={session.id}>
              <div className="session-icon">
                <CalendarDays size={22} />
              </div>
              <span className="tag">{session.className}</span>
              <h3>{session.courseName}</h3>
              <p>
                {session.teacherName} · {session.room}
              </p>
              <p>
                {new Date(session.startsAt).toLocaleDateString('zh-CN')} {time(session.startsAt)}—
                {time(session.endsAt)}
              </p>
              <div className="session-bottom">
                <span>
                  <Users size={15} /> {session.scheduledUserIds.length} 位学生
                </span>
                <button className="text-button" onClick={() => setEditing(session)}>
                  安排学生 <ArrowRight size={15} />
                </button>
              </div>
            </article>
          ))}
        </div>
      </Panel>
      {editing && (
        <ScheduleDialog session={editing} data={data} save={save} close={() => setEditing(null)} />
      )}
    </>
  );
}

function StatisticsPage({ data, records }: { data: WorkspaceData; records: EmojiRecord[] }) {
  const [course, setCourse] = useState('');
  const [className, setClassName] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const invalid = Boolean(from && to && from > to);
  const filtered = records.filter((record) => {
    const session = data.sessions.find((item) => item.id === record.sessionId);
    const day = new Date(record.recordedAt).toLocaleDateString('sv-SE');
    return (
      !invalid &&
      (!course || session?.courseId === course) &&
      (!className || session?.className === className) &&
      (!from || day >= from) &&
      (!to || day <= to)
    );
  });
  return (
    <>
      <Panel
        title="多维统计"
        description={`当前筛选共 ${filtered.length} 条情绪记录`}
        action={
          <button
            className="button secondary"
            onClick={() => {
              setCourse('');
              setClassName('');
              setFrom('');
              setTo('');
            }}
          >
            重置筛选
          </button>
        }
      >
        <div className="filters">
          <select
            aria-label="筛选课程"
            value={course}
            onChange={(event) => setCourse(event.target.value)}
          >
            <option value="">全部课程</option>
            {[
              ...new Map(
                data.sessions.map((session) => [session.courseId, session.courseName]),
              ).entries(),
            ].map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
          <select
            aria-label="筛选班级"
            value={className}
            onChange={(event) => setClassName(event.target.value)}
          >
            <option value="">全部班级</option>
            {[...new Set(data.sessions.map((session) => session.className))].map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
          <label className="date-filter">
            从{' '}
            <input
              aria-label="开始日期"
              type="date"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
            />
          </label>
          <label className="date-filter">
            至{' '}
            <input
              aria-label="结束日期"
              type="date"
              value={to}
              onChange={(event) => setTo(event.target.value)}
            />
          </label>
        </div>
        {invalid && <p className="error">结束日期不能早于开始日期。</p>}
      </Panel>
      <div className="two-columns">
        <Panel title="情绪构成">
          <EmotionChart records={filtered} />
        </Panel>
        <Panel title="反馈时间分布">
          <Trend records={filtered} />
        </Panel>
      </div>
      <Panel title="按课程与班级汇总">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>课程 / 班级</th>
                <th>总记录</th>
                <th>手动提交</th>
                <th>AI 识别</th>
              </tr>
            </thead>
            <tbody>
              {[
                ...new Map(
                  data.sessions.map((session) => [
                    `${session.courseId}-${session.className}`,
                    session,
                  ]),
                ).values(),
              ].map((session) => {
                const rows = filtered.filter((record) => {
                  const item = data.sessions.find((value) => value.id === record.sessionId);
                  return (
                    item?.courseId === session.courseId && item.className === session.className
                  );
                });
                return (
                  <tr key={`${session.courseId}-${session.className}`}>
                    <td>
                      {session.courseName}
                      <small>{session.className}</small>
                    </td>
                    <td>{rows.length}</td>
                    <td>{rows.filter((row) => row.source === 'MANUAL').length}</td>
                    <td>{rows.filter((row) => row.source === 'AI').length}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

export function App() {
  const { data, loading, error, reload, schedule } = useWorkspace();
  const [page, setPage] = useState<Page>(readPage);
  const [sessionId, setSessionId] = useState('');
  const [mobileOpen, setMobileOpen] = useState(false);
  const [help, setHelp] = useState(false);
  useEffect(() => {
    const change = () => setPage(readPage());
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  const go = (next: Page) => {
    location.hash = next;
    setPage(next);
    setMobileOpen(false);
  };
  const active = pages.find((item) => item.id === page)!;
  const records = data ? sessionRecords(data, sessionId) : [];
  return (
    <div className="app">
      <aside className={`sidebar ${mobileOpen ? 'open' : ''}`}>
        <a className="brand" href="#dashboard" onClick={() => go('dashboard')}>
          <span className="brand-symbol">
            <Smile size={25} />
          </span>
          <span>
            课堂心晴<small>CLASSROOM MOOD</small>
          </span>
        </a>
        <div className="workspace-name">
          <span className="workspace-avatar">课</span>
          <div>
            课堂情绪管理<small>软件工程实践项目</small>
          </div>
          <ChevronDown size={14} />
        </div>
        <p className="nav-caption">工作空间</p>
        <nav>
          {pages.map((item) => (
            <button
              key={item.id}
              className={page === item.id ? 'active' : ''}
              onClick={() => go(item.id)}
            >
              <item.icon size={19} />
              {item.label}
              {page === item.id && <span className="active-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-note">
            <Smile size={22} />
            <p>
              看见情绪，关心成长。<small>AI 默认匿名 · 不存原始影像</small>
            </p>
          </div>
          <button className="help-button" onClick={() => setHelp((current) => !current)}>
            <CircleHelp size={18} />
            框架使用说明
          </button>
          <div className="profile">
            <span className="profile-avatar">组</span>
            <div>
              组长工作空间<small>管理端开发</small>
            </div>
            <span className="profile-dot" />
          </div>
        </div>
      </aside>
      {mobileOpen && (
        <button
          className="mobile-backdrop"
          aria-label="收起菜单"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <div className="main-layout">
        <header>
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              aria-label="打开菜单"
              onClick={() => setMobileOpen(true)}
            >
              <Menu size={20} />
            </button>
            <span>工作空间</span>
            <span>/</span>
            <strong>{active.label}</strong>
          </div>
          <div className="header-right">
            <span className={`mode-badge ${isDemo ? '' : 'api'}`}>
              <i />
              {isDemo ? '演示模式' : 'API 模式'}
            </span>
            <span className="header-avatar">组</span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">CLASSROOM MOOD CHECKER</div>
              <h1>{active.label}</h1>
              <p>
                {page === 'dashboard'
                  ? '每一份课堂反馈，都是更好教学的起点。'
                  : '让课堂数据清晰、有序，便于团队继续完善。'}
              </p>
            </div>
            <div className="page-actions">
              {(page === 'dashboard' || page === 'records' || page === 'statistics') && data && (
                <select
                  aria-label="选择课堂"
                  value={sessionId}
                  onChange={(event) => setSessionId(event.target.value)}
                >
                  <option value="">全部课堂</option>
                  {data.sessions.map((session) => (
                    <option key={session.id} value={session.id}>
                      {session.courseName} · {time(session.startsAt)}
                    </option>
                  ))}
                </select>
              )}
              <button className="button secondary" onClick={() => void reload()} disabled={loading}>
                <RefreshCw size={15} className={loading ? 'spinning' : ''} />
                刷新
              </button>
            </div>
          </div>
          <div className="notice">
            <span className="notice-dot" />
            {isDemo
              ? '当前为本地演示数据。筛选、CSV 导出和课堂学生安排可操作，尚未连接真实账号与 AI。'
              : '已切换 API 模式。业务接口与认证接入待后端实现，错误会在此页显示。'}
          </div>
          {help && (
            <div className="help-panel">
              <h2>从这里开始开发</h2>
              <p>
                管理端按 views、controllers、models、repositories 分层。默认演示模式可独立运行；通过
                .env.local 中的 VITE_DATA_MODE=api 切换接口模式。后端接口文档位于
                http://127.0.0.1:8000/docs，完整说明见仓库 README。
              </p>
              <button className="text-button" onClick={() => setHelp(false)}>
                收起说明
              </button>
            </div>
          )}
          {loading ? (
            <div className="empty">正在加载课堂数据…</div>
          ) : error ? (
            <div className="error-panel">
              <h2>暂时无法加载数据</h2>
              <p>{error}</p>
              <button className="button" onClick={() => void reload()}>
                重新加载
              </button>
            </div>
          ) : (
            data && (
              <div className="page-content" key={page}>
                {page === 'dashboard' && <Dashboard data={data} records={records} go={go} />}
                {page === 'users' && <UsersPage data={data} />}
                {page === 'records' && <RecordsPage data={data} records={records} />}
                {page === 'sessions' && <SessionsPage data={data} save={schedule} />}
                {page === 'statistics' && <StatisticsPage data={data} records={records} />}
              </div>
            )
          )}
          <footer>
            <span>课堂心晴 · 表情符号课堂情绪检查器系统</span>
            <span>框架 v0.1 · {new Date().getFullYear()}</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
