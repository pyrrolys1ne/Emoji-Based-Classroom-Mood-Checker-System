import {
  emotions,
  type User,
  type ClassSession,
  type EmojiRecord,
  type Emotion,
} from '@mood/contracts';
import { ClientError, type ClientRepository, type EmotionStatistics } from '../models/client';

const keys = Object.keys(emotions) as Emotion[];
const obj = (x: unknown): x is Record<string, any> =>
  typeof x === 'object' && x !== null && !Array.isArray(x);
const str = (x: unknown): x is string => typeof x === 'string' && x.length > 0;
const time = (x: unknown) =>
  str(x) && /(?:Z|[+-]\d\d:\d\d)$/.test(x) && Number.isFinite(Date.parse(x));
const emotion = (x: unknown): x is Emotion => typeof x === 'string' && keys.includes(x as Emotion);
const user = (x: unknown): x is User =>
  obj(x) &&
  str(x.id) &&
  str(x.username) &&
  str(x.email) &&
  ['STUDENT', 'TEACHER', 'ADMIN'].includes(x.role) &&
  ['ACTIVE', 'DISABLED'].includes(x.status);
const session = (x: unknown): x is ClassSession =>
  obj(x) &&
  ['id', 'courseId', 'courseName', 'teacherName', 'className', 'room'].every((k) => str(x[k])) &&
  time(x.startsAt) &&
  time(x.endsAt) &&
  Date.parse(x.startsAt) < Date.parse(x.endsAt) &&
  Array.isArray(x.scheduledUserIds) &&
  x.scheduledUserIds.every(str);
const record = (x: unknown): x is EmojiRecord =>
  obj(x) &&
  str(x.id) &&
  (x.userId === null || str(x.userId)) &&
  str(x.sessionId) &&
  emotion(x.emotion) &&
  ['MANUAL', 'AI'].includes(x.source) &&
  (x.confidence === null ||
    (typeof x.confidence === 'number' &&
      Number.isFinite(x.confidence) &&
      x.confidence >= 0 &&
      x.confidence <= 1)) &&
  time(x.recordedAt) &&
  (x.simulated === undefined || typeof x.simulated === 'boolean') &&
  (x.inferenceProvider === undefined ||
    x.inferenceProvider === null ||
    ['DeepSeek', 'DeepFace'].includes(x.inferenceProvider)) &&
  (x.confidenceKind === undefined ||
    x.confidenceKind === null ||
    ['self_reported', 'model_score'].includes(x.confidenceKind));
const stats = (x: unknown): x is EmotionStatistics =>
  obj(x) &&
  Number.isSafeInteger(x.total) &&
  x.total >= 0 &&
  obj(x.distribution) &&
  keys.every((k) => Number.isSafeInteger(x.distribution[k]) && x.distribution[k] >= 0) &&
  keys.reduce((a, k) => a + x.distribution[k], 0) === x.total;
const bad = () => new ClientError('服务返回的数据格式无效。', 0, 'INVALID_RESPONSE');
const cleanUser = (u: User): User => ({
  id: u.id,
  username: u.username,
  email: u.email,
  role: u.role,
  status: u.status,
});

export function createApiRepository(
  options: { baseUrl?: string; fetcher?: typeof fetch; timeoutMs?: number } = {},
): ClientRepository {
  const base = (options.baseUrl ?? '/api').replace(/\/$/, '');
  const fetcher = options.fetcher ?? fetch;
  async function request(
    path: string,
    method: string,
    token?: string,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<unknown> {
    const controller = new AbortController();
    let timedOut = false;
    const abort = () => controller.abort();
    if (signal?.aborted) controller.abort();
    else signal?.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, options.timeoutMs ?? 15000);
    try {
      const headers: Record<string, string> = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      const response = await fetcher(base + path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      let envelope: unknown;
      try {
        envelope = await response.json();
      } catch {
        throw new ClientError(
          '服务响应无法读取，请稍后重试。',
          response.status,
          'INVALID_RESPONSE',
        );
      }
      if (!obj(envelope) || typeof envelope.code !== 'string')
        throw new ClientError('服务返回的数据格式无效。', response.status, 'INVALID_RESPONSE');
      if (!response.ok || envelope.code !== 'OK') {
        const messages: Record<number, string> = {
          401: '身份已失效或账号密码错误，请重新登录。',
          403: '没有权限执行此操作。',
          404: '请求的内容不存在。',
          409: '操作与当前状态冲突。',
          422: '提交的信息无效。',
          501: '此功能尚未开放。',
          503: '服务暂时不可用。',
        };
        throw new ClientError(
          messages[response.status] ?? '操作未能完成，请稍后重试。',
          response.status,
          /^[A-Z0-9_]{1,80}$/.test(envelope.code) ? envelope.code : 'REQUEST_FAILED',
        );
      }
      return envelope.data;
    } catch (e) {
      if (e instanceof ClientError) throw e;
      if (controller.signal.aborted)
        throw new ClientError(
          timedOut ? '请求超时，结果可能未知，请核实后重试。' : '请求已取消。',
          0,
          timedOut ? 'TIMEOUT' : 'ABORTED',
        );
      throw new ClientError('网络连接失败，请稍后重试。', 0, 'NETWORK_ERROR');
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
  }
  return {
    mode: 'api',
    async login(i, s) {
      const d = await request(
        '/auth/login',
        'POST',
        undefined,
        { username: i.username, password: i.password },
        s,
      );
      if (!obj(d) || !str(d.token) || !user(d.user)) throw bad();
      return { token: d.token, user: cleanUser(d.user) };
    },
    async register(i, s) {
      await request(
        '/auth/register',
        'POST',
        undefined,
        { username: i.username, email: i.email, password: i.password, role: i.role },
        s,
      );
    },
    async me(t, s) {
      const d = await request('/users/me', 'GET', t, undefined, s);
      if (!user(d)) throw bad();
      return cleanUser(d);
    },
    async logout(t, s) {
      await request('/auth/logout', 'POST', t, undefined, s);
    },
    async changePassword(t, i, s) {
      await request(
        '/auth/password',
        'PUT',
        t,
        { oldPassword: i.oldPassword, newPassword: i.newPassword },
        s,
      );
    },
    async sessions(t, s) {
      const d = await request('/sessions', 'GET', t, undefined, s);
      if (!Array.isArray(d) || !d.every(session)) throw bad();
      return d;
    },
    async submit(t, id, e, s) {
      await request('/emoji', 'POST', t, { sessionId: id, emotion: e }, s);
    },
    async history(t, id, s) {
      const d = await request(
        '/emoji/history' + (id ? `?sessionId=${encodeURIComponent(id)}` : ''),
        'GET',
        t,
        undefined,
        s,
      );
      if (!Array.isArray(d) || !d.every(record)) throw bad();
      return d;
    },
    async statistics(t, id, s) {
      const d = await request(
        `/emoji/statistics?sessionId=${encodeURIComponent(id)}`,
        'GET',
        t,
        undefined,
        s,
      );
      if (!stats(d)) throw bad();
      return d;
    },
  };
}

type DemoUser = User & { salt: string; hash: string };
type Store = {
  version: 2;
  users: DemoUser[];
  sessions: ClassSession[];
  teachers: Record<string, string>;
  records: EmojiRecord[];
  tokens: Record<string, { userId: string; expires: number }>;
};
const storeKey = 'mood-client-demo-v2';
// WeakMap serializes instances sharing a Storage object in this JavaScript realm.
const demoQueues = new WeakMap<Storage, Promise<void>>();
async function serializeDemo<T>(storage: Storage, work: () => Promise<T>): Promise<T> {
  const previous = demoQueues.get(storage) ?? Promise.resolve();
  let release!: () => void;
  const next = new Promise<void>((resolve) => {
    release = resolve;
  });
  demoQueues.set(storage, next);
  await previous;
  try {
    // Custom Storage objects (such as in-memory tests) must not acquire a global browser lock.
    let isLocal = false;
    try {
      isLocal = typeof localStorage !== 'undefined' && storage === localStorage;
    } catch {
      /* unavailable */
    }
    if (isLocal && typeof navigator !== 'undefined' && navigator.locks) {
      return await navigator.locks.request(storeKey, work);
    }
    return await work();
  } finally {
    release();
    if (demoQueues.get(storage) === next) demoQueues.delete(storage);
  }
}
const id = () => crypto.randomUUID();
const hex = (bytes: Uint8Array) =>
  Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
async function digest(password: string, salt: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(password),
    'PBKDF2',
    false,
    ['deriveBits'],
  );
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt: new TextEncoder().encode(salt), iterations: 100000 },
    key,
    256,
  );
  return hex(new Uint8Array(bits));
}
const salt = () => hex(crypto.getRandomValues(new Uint8Array(16)));
const fail = (message: string, status: number, code: string): never => {
  throw new ClientError(message, status, code);
};
export function createDemoRepository(
  options: { storage?: Storage; now?: () => number; delayMs?: number } = {},
): ClientRepository {
  const now = options.now ?? Date.now;
  let storage: Storage;
  try {
    storage = options.storage ?? localStorage;
  } catch {
    throw new ClientError('演示数据存储不可用。', 0, 'STORAGE_ERROR');
  }
  const check = (s?: AbortSignal) => {
    if (s?.aborted) fail('请求已取消。', 0, 'ABORTED');
  };
  async function pause(s?: AbortSignal) {
    check(s);
    if (options.delayMs)
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => {
          s?.removeEventListener('abort', cancel);
          resolve();
        }, options.delayMs);
        const cancel = () => {
          clearTimeout(timer);
          reject(new ClientError('请求已取消。', 0, 'ABORTED'));
        };
        s?.addEventListener('abort', cancel, { once: true });
      });
    check(s);
  }
  function valid(x: unknown): x is Store {
    return (
      obj(x) &&
      x.version === 2 &&
      Array.isArray(x.users) &&
      x.users.every((u: unknown) => obj(u) && str(u.salt) && str(u.hash) && user(u)) &&
      Array.isArray(x.sessions) &&
      x.sessions.every(session) &&
      Array.isArray(x.records) &&
      x.records.every(record) &&
      obj(x.teachers) &&
      Object.values(x.teachers).every(str) &&
      obj(x.tokens) &&
      Object.values(x.tokens).every(
        (t: unknown) =>
          obj(t) && str(t.userId) && typeof t.expires === 'number' && Number.isFinite(t.expires),
      )
    );
  }
  function save(x: Store, s?: AbortSignal) {
    check(s);
    if (!valid(x)) throw bad();
    try {
      storage.setItem(storeKey, JSON.stringify(x));
    } catch {
      fail('演示数据存储不可用。', 0, 'STORAGE_ERROR');
    }
  }
  async function load(s?: AbortSignal): Promise<Store> {
    check(s);
    let raw: string | null;
    try {
      raw = storage.getItem(storeKey);
    } catch {
      return fail('演示数据存储不可用。', 0, 'STORAGE_ERROR');
    }
    if (raw !== null) {
      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch {
        return fail('演示数据损坏，请检查本地存储。', 0, 'STORAGE_CORRUPT');
      }
      if (!valid(parsed)) return fail('演示数据损坏，请检查本地存储。', 0, 'STORAGE_CORRUPT');
      return parsed;
    }
    const users: DemoUser[] = [];
    for (const [username, role] of [
      ['student-a', 'STUDENT'],
      ['student-b', 'STUDENT'],
      ['teacher-a', 'TEACHER'],
      ['teacher-b', 'TEACHER'],
    ] as const) {
      const st = salt();
      users.push({
        id: id(),
        username,
        email: `${username}@demo.invalid`,
        role,
        status: 'ACTIVE',
        salt: st,
        hash: await digest('classroom-demo-2026', st),
      });
    }
    const n = now(),
      date = (offset: number) => new Date(n + offset).toISOString();
    const make = (
      name: string,
      teacher: DemoUser,
      students: DemoUser[],
      start: number,
      end: number,
    ): ClassSession => ({
      id: id(),
      courseId: id(),
      courseName: name,
      teacherName: teacher.username,
      className: '演示班级',
      room: '演示教室',
      startsAt: date(start),
      endsAt: date(end),
      scheduledUserIds: students.map((u) => u.id),
    });
    const sessions = [
      make('演示课堂', users[2], [users[0], users[1]], -86400000, 30 * 86400000),
      make('历史课堂', users[2], [users[0]], -3 * 86400000, -2 * 86400000),
      make('另一教师课堂', users[3], [users[1]], -86400000, 30 * 86400000),
    ];
    const x: Store = {
      version: 2,
      users,
      sessions,
      teachers: {
        [sessions[0].id]: users[2].id,
        [sessions[1].id]: users[2].id,
        [sessions[2].id]: users[3].id,
      },
      records: [],
      tokens: {},
    };
    // Do not overwrite a store initialized by another concurrent operation.
    check(s);
    try {
      if (storage.getItem(storeKey) !== null) return load(s);
    } catch {
      return fail('演示数据存储不可用。', 0, 'STORAGE_ERROR');
    }
    save(x, s);
    return x;
  }
  function auth(x: Store, t: string): DemoUser {
    const entry = x.tokens[t];
    const u = entry && x.users.find((v) => v.id === entry.userId);
    if (!entry || entry.expires <= now() || !u || u.status !== 'ACTIVE')
      return fail('登录已失效，请重新登录。', 401, 'UNAUTHORIZED');
    return u;
  }
  const allowed = (x: Store, u: DemoUser, sessionId: string) => {
    const c = x.sessions.find((v) => v.id === sessionId);
    if (
      !c ||
      (u.role === 'STUDENT'
        ? !c.scheduledUserIds.includes(u.id)
        : u.role !== 'TEACHER' || x.teachers[c.id] !== u.id)
    )
      return fail('没有权限访问此课堂。', 403, 'FORBIDDEN');
    return c;
  };
  const repository: ClientRepository = {
    mode: 'demo',
    async login(i, s) {
      await pause(s);
      const x = await load(s);
      const u = x.users.find((v) => v.username === i.username);
      if (!u || (await digest(i.password, u.salt)) !== u.hash)
        return fail('账号或密码错误。', 401, 'UNAUTHORIZED');
      if (u.status !== 'ACTIVE')
        return fail('账号尚未获准使用，请等待教师申请审核。', 403, 'ACCOUNT_PENDING');
      const token = id();
      x.tokens[token] = { userId: u.id, expires: now() + 8 * 3600000 };
      save(x, s);
      return { token, user: cleanUser(u) };
    },
    async register(i, s) {
      await pause(s);
      const x = await load(s);
      if (
        !['STUDENT', 'TEACHER'].includes(i.role) ||
        i.username.length < 2 ||
        i.username.length > 50 ||
        i.password.length < 8 ||
        i.password.length > 128 ||
        !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(i.email)
      )
        return fail('注册信息无效。', 422, 'INVALID_INPUT');
      if (
        x.users.some(
          (u) =>
            u.username.toLowerCase() === i.username.toLowerCase() ||
            u.email.toLowerCase() === i.email.toLowerCase(),
        )
      )
        return fail('用户名或邮箱已存在。', 409, 'DUPLICATE');
      const st = salt();
      const u: DemoUser = {
        id: id(),
        username: i.username,
        email: i.email,
        role: i.role,
        status: i.role === 'TEACHER' ? 'DISABLED' : 'ACTIVE',
        salt: st,
        hash: await digest(i.password, st),
      };
      x.users.push(u);
      if (u.role === 'STUDENT') x.sessions[0].scheduledUserIds.push(u.id);
      save(x, s);
    },
    async me(t, s) {
      await pause(s);
      return cleanUser(auth(await load(s), t));
    },
    async logout(t, s) {
      await pause(s);
      const x = await load(s);
      auth(x, t);
      delete x.tokens[t];
      save(x, s);
    },
    async changePassword(t, i, s) {
      await pause(s);
      const x = await load(s);
      const u = auth(x, t);
      if ((await digest(i.oldPassword, u.salt)) !== u.hash)
        return fail('原密码错误。', 403, 'INVALID_PASSWORD');
      if (i.newPassword.length < 8 || i.newPassword.length > 128)
        return fail('新密码长度应为 8 至 128 位。', 422, 'INVALID_INPUT');
      u.salt = salt();
      u.hash = await digest(i.newPassword, u.salt);
      for (const [token, entry] of Object.entries(x.tokens))
        if (entry.userId === u.id) delete x.tokens[token];
      save(x, s);
    },
    async sessions(t, s) {
      await pause(s);
      const x = await load(s),
        u = auth(x, t);
      return x.sessions.filter((c) =>
        u.role === 'STUDENT'
          ? c.scheduledUserIds.includes(u.id)
          : u.role === 'TEACHER' && x.teachers[c.id] === u.id,
      );
    },
    async submit(t, sessionId, e, s) {
      await pause(s);
      const x = await load(s),
        u = auth(x, t);
      if (u.role !== 'STUDENT') return fail('只有学生可以提交反馈。', 403, 'FORBIDDEN');
      const c = allowed(x, u, sessionId);
      if (!emotion(e)) return fail('情绪无效。', 422, 'INVALID_INPUT');
      if (now() < Date.parse(c.startsAt) || now() >= Date.parse(c.endsAt))
        return fail('课堂当前不接受反馈。', 409, 'SESSION_CLOSED');
      x.records.push({
        id: id(),
        userId: u.id,
        sessionId,
        emotion: e,
        source: 'MANUAL',
        confidence: null,
        recordedAt: new Date(now()).toISOString(),
        simulated: true,
      });
      save(x, s);
    },
    async history(t, sessionId, s) {
      await pause(s);
      const x = await load(s),
        u = auth(x, t);
      if (sessionId) allowed(x, u, sessionId);
      return x.records.filter(
        (r) =>
          (!sessionId || r.sessionId === sessionId) &&
          (u.role === 'STUDENT'
            ? r.userId === u.id
            : u.role === 'TEACHER' && x.teachers[r.sessionId] === u.id),
      );
    },
    async statistics(t, sessionId, s) {
      await pause(s);
      const x = await load(s),
        u = auth(x, t);
      if (u.role !== 'TEACHER') return fail('只有任课教师可以查看统计。', 403, 'FORBIDDEN');
      allowed(x, u, sessionId);
      const records = x.records.filter((r) => r.sessionId === sessionId);
      const distribution = Object.fromEntries(keys.map((k) => [k, 0])) as Record<Emotion, number>;
      for (const r of records) distribution[r.emotion]++;
      return { total: records.length, distribution };
    },
  };
  return {
    mode: 'demo',
    login: (...args) => serializeDemo(storage, () => repository.login(...args)),
    register: (...args) => serializeDemo(storage, () => repository.register(...args)),
    me: (...args) => serializeDemo(storage, () => repository.me(...args)),
    logout: (...args) => serializeDemo(storage, () => repository.logout(...args)),
    changePassword: (...args) => serializeDemo(storage, () => repository.changePassword(...args)),
    sessions: (...args) => serializeDemo(storage, () => repository.sessions(...args)),
    submit: (...args) => serializeDemo(storage, () => repository.submit(...args)),
    history: (...args) => serializeDemo(storage, () => repository.history(...args)),
    statistics: (...args) => serializeDemo(storage, () => repository.statistics(...args)),
  };
}
