import { emotions, type ApiResponse, type WorkspaceData } from '@mood/contracts';

export const isDemo = (import.meta.env.VITE_DATA_MODE ?? 'demo') === 'demo';
const base = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '');
const storageKey = 'mood-demo-schedules-v1';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  const body = (await response.json()) as ApiResponse<T>;
  if (!response.ok) throw new Error(body.message ?? `请求失败：${response.status}`);
  return body.data;
}

function seed(): WorkspaceData {
  const users: WorkspaceData['users'] = Array.from({ length: 12 }, (_, index) => ({
    id: `student-${index + 1}`,
    username: [
      '林晓',
      '陈雨',
      '李明',
      '王悦',
      '张晨',
      '刘洋',
      '赵宁',
      '周可',
      '吴桐',
      '徐安',
      '孙晴',
      '胡宇',
    ][index],
    email: `student${index + 1}@example.edu`,
    role: 'STUDENT',
    status: 'ACTIVE',
  }));
  users.push(
    {
      id: 'teacher-1',
      username: '陈老师',
      email: 'teacher@example.edu',
      role: 'TEACHER',
      status: 'ACTIVE',
    },
    {
      id: 'admin-1',
      username: '演示管理员',
      email: 'admin@example.edu',
      role: 'ADMIN',
      status: 'ACTIVE',
    },
  );
  const at = (hour: number, minute = 0) => {
    const date = new Date();
    date.setHours(hour, minute, 0, 0);
    return date.toISOString();
  };
  const sessions: WorkspaceData['sessions'] = [
    {
      id: 'session-1',
      courseId: 'course-1',
      courseName: '软件工程实践',
      teacherName: '陈老师',
      className: '软件工程 2301',
      room: '实训楼 302',
      startsAt: at(9),
      endsAt: at(10, 40),
      scheduledUserIds: users.slice(0, 12).map((user) => user.id),
    },
    {
      id: 'session-2',
      courseId: 'course-2',
      courseName: '数据库系统',
      teacherName: '陈老师',
      className: '软件工程 2302',
      room: '教学楼 A205',
      startsAt: at(14),
      endsAt: at(15, 40),
      scheduledUserIds: users.slice(0, 8).map((user) => user.id),
    },
    {
      id: 'session-3',
      courseId: 'course-1',
      courseName: '软件工程实践',
      teacherName: '陈老师',
      className: '软件工程 2301',
      room: '实训楼 302',
      startsAt: at(16),
      endsAt: at(17, 40),
      scheduledUserIds: users.slice(0, 12).map((user) => user.id),
    },
  ];
  const keys = Object.keys(emotions) as (keyof typeof emotions)[];
  const records: WorkspaceData['records'] = Array.from({ length: 96 }, (_, index) => {
    const session = sessions[index < 64 ? 0 : 1];
    const ai = index % 4 === 0;
    return {
      id: `record-${index + 1}`,
      userId: ai ? null : users[index % 12].id,
      sessionId: session.id,
      emotion: keys[[0, 1, 0, 2, 1, 3, 0, 1, 4, 2, 1, 0][index % 12]],
      source: ai ? 'AI' : 'MANUAL',
      confidence: ai ? Number((0.8 + (index % 19) / 100).toFixed(2)) : null,
      recordedAt: new Date(Date.parse(session.startsAt) + (index % 60) * 60000).toISOString(),
    };
  });
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? '{}') as Record<string, string[]>;
    for (const session of sessions)
      if (Array.isArray(saved[session.id]))
        session.scheduledUserIds = saved[session.id].filter((id) =>
          users.some((user) => user.id === id && user.role === 'STUDENT'),
        );
  } catch {
    /* 损坏或受限的浏览器存储不影响演示启动。 */
  }
  return { users, sessions, records };
}

export const workspaceRepository = {
  async load(): Promise<WorkspaceData> {
    if (isDemo) return seed();
    const [users, sessions, records] = await Promise.all([
      request<WorkspaceData['users']>('/admin/users'),
      request<WorkspaceData['sessions']>('/sessions'),
      request<WorkspaceData['records']>('/emoji/history'),
    ]);
    return { users, sessions, records };
  },
  async schedule(sessionId: string, userIds: string[]): Promise<void> {
    if (!isDemo)
      return request<void>(`/admin/sessions/${encodeURIComponent(sessionId)}/schedule`, {
        method: 'POST',
        body: JSON.stringify({ userIds }),
      });
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? '{}') as Record<string, string[]>;
    localStorage.setItem(storageKey, JSON.stringify({ ...saved, [sessionId]: userIds }));
  },
};
