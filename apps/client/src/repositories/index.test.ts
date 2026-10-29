import { describe, it, expect } from 'vitest';
import { createApiRepository, createDemoRepository } from './index';
import { ClientError } from '../models/client';

function memory(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear() {
      m.clear();
    },
    getItem(k) {
      return m.get(k) ?? null;
    },
    key(i) {
      return [...m.keys()][i] ?? null;
    },
    removeItem(k) {
      m.delete(k);
    },
    setItem(k, v) {
      m.set(k, String(v));
    },
  };
}

it('isolates unapproved active teachers from the legacy demo namespace without deleting it', async () => {
  const storage = memory();
  const repo = createDemoRepository({ storage });
  const input = {
    username: 'legacy-teacher',
    password: 'synthetic-password',
    email: 'legacy@example.test',
    role: 'TEACHER' as const,
  };
  await repo.register(input);
  const old = JSON.parse(storage.getItem('mood-client-demo-v2')!);
  old.version = 1;
  old.users.find(
    (value: { username: string; status: string }) => value.username === input.username,
  ).status = 'ACTIVE';
  const legacy = JSON.stringify(old);
  storage.setItem('mood-client-demo-v1', legacy);
  storage.removeItem('mood-client-demo-v2');
  await expect(createDemoRepository({ storage }).login(input)).rejects.toMatchObject({
    status: 401,
  });
  expect(storage.getItem('mood-client-demo-v1')).toBe(legacy);
});
describe('API repository', () => {
  it('preserves an unauthorized HTTP status even when the JSON envelope is malformed', async () => {
    const fetcher = (async () =>
      new Response(JSON.stringify({ message: 'unauthorized' }), { status: 401 })) as typeof fetch;
    await expect(createApiRepository({ fetcher }).me('synthetic-token')).rejects.toMatchObject({
      status: 401,
      code: 'INVALID_RESPONSE',
    });
  });
  it('sends only submission fields with bearer authentication', async () => {
    let request: RequestInit | undefined;
    const fetcher = (async (_: RequestInfo | URL, init?: RequestInit) => {
      request = init;
      return new Response(JSON.stringify({ code: 'OK', data: null }), { status: 200 });
    }) as typeof fetch;
    await createApiRepository({ fetcher }).submit('token', 'class', 'HAPPY');
    expect(JSON.parse(request!.body as string)).toEqual({ sessionId: 'class', emotion: 'HAPPY' });
    expect((request!.headers as Record<string, string>).Authorization).toBe('Bearer token');
  });
  it('rejects bad shape and error envelopes without exposing backend message', async () => {
    const fetcher = (async () =>
      new Response(JSON.stringify({ code: 'OK', data: { items: [] } }))) as typeof fetch;
    await expect(createApiRepository({ fetcher }).sessions('t')).rejects.toMatchObject({
      code: 'INVALID_RESPONSE',
    });
    const badFetcher = (async () =>
      new Response(JSON.stringify({ code: 'BAD', message: 'secret stack' }), {
        status: 409,
      })) as typeof fetch;
    await expect(
      createApiRepository({ fetcher: badFetcher }).register({
        username: 'u',
        email: 'a@b.c',
        password: 'password',
        role: 'STUDENT',
      }),
    ).rejects.toMatchObject({
      status: 409,
      code: 'BAD',
      message: expect.not.stringContaining('secret'),
    });
  });
});
describe('demo repository', () => {
  it('isolates students and teachers, persists and revokes sessions', async () => {
    const storage = memory();
    const repo = createDemoRepository({ storage, now: () => 1700000000000 });
    const a = await repo.login({ username: 'student-a', password: 'classroom-demo-2026' });
    const b = await repo.login({ username: 'student-b', password: 'classroom-demo-2026' });
    const ta = await repo.login({ username: 'teacher-a', password: 'classroom-demo-2026' });
    const tb = await repo.login({ username: 'teacher-b', password: 'classroom-demo-2026' });
    const classes = await repo.sessions(a.token);
    await repo.submit(a.token, classes[0].id, 'HAPPY');
    expect(await repo.history(b.token)).toHaveLength(0);
    expect(await repo.statistics(ta.token, classes[0].id)).toMatchObject({ total: 1 });
    await expect(repo.statistics(tb.token, classes[0].id)).rejects.toBeInstanceOf(ClientError);
    await expect(repo.submit(a.token, classes[1].id, 'HAPPY')).rejects.toMatchObject({
      status: 409,
    });
    expect(
      await createDemoRepository({ storage, now: () => 1700000000000 }).history(a.token),
    ).toHaveLength(1);
    expect(storage.getItem('mood-client-demo-v2')).not.toContain('classroom-demo-2026');
    await repo.changePassword(a.token, {
      oldPassword: 'classroom-demo-2026',
      newPassword: 'new-password',
    });
    await expect(repo.me(a.token)).rejects.toMatchObject({ status: 401 });
    await repo.logout(b.token);
    await expect(repo.me(b.token)).rejects.toMatchObject({ status: 401 });
  });
});

it('serializes concurrent writes across repositories sharing storage', async () => {
  const storage = memory(),
    now = () => 1700000000000;
  const first = createDemoRepository({ storage, now }),
    second = createDemoRepository({ storage, now });
  const a = await first.login({ username: 'student-a', password: 'classroom-demo-2026' });
  const classId = (await first.sessions(a.token))[0].id;
  await Promise.all(
    Array.from({ length: 12 }, (_, i) =>
      (i % 2 ? first : second).submit(a.token, classId, 'HAPPY'),
    ),
  );
  expect(await second.history(a.token, classId)).toHaveLength(12);
});

describe('API boundary coverage', () => {
  const user = {
    id: 'u',
    username: 'student',
    email: 's@example.test',
    role: 'STUDENT',
    status: 'ACTIVE',
    extra: 'private',
  };
  const distribution = Object.fromEntries(
    ['HAPPY', 'FOCUSED', 'NEUTRAL', 'CONFUSED', 'SAD', 'ANGRY', 'SURPRISED', 'FEAR', 'DISGUST'].map(
      (k) => [k, 0],
    ),
  );
  function response(data: unknown, code = 'OK', status = 200) {
    return new Response(JSON.stringify({ code, message: 'secret password stack', data }), {
      status,
    });
  }
  it('uses exact paths, methods, bodies and authentication', async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    const fetcher = (async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), init: init! });
      const p = String(url);
      return response(
        p.endsWith('/login')
          ? { token: 't', user }
          : p.endsWith('/me')
            ? user
            : p.includes('/statistics')
              ? { total: 0, distribution }
              : p.endsWith('/sessions') || p.includes('/history')
                ? []
                : null,
      );
    }) as typeof fetch;
    const repo = createApiRepository({ baseUrl: '/api/', fetcher });
    await repo.login({ username: 'alice', password: 'sensitive' });
    await repo.register({
      username: 'alice',
      password: 'sensitive',
      email: 'a@b.test',
      role: 'STUDENT',
    });
    expect(await repo.me('tok')).toEqual({
      id: 'u',
      username: 'student',
      email: 's@example.test',
      role: 'STUDENT',
      status: 'ACTIVE',
    });
    await repo.logout('tok');
    await repo.changePassword('tok', { oldPassword: 'oldsecret', newPassword: 'newsecret' });
    await repo.sessions('tok');
    await repo.submit('tok', 'a/b', 'HAPPY');
    await repo.history('tok', 'a/b');
    await repo.statistics('tok', 'a/b');
    expect(calls.map((c) => [c.url, c.init.method])).toEqual([
      ['/api/auth/login', 'POST'],
      ['/api/auth/register', 'POST'],
      ['/api/users/me', 'GET'],
      ['/api/auth/logout', 'POST'],
      ['/api/auth/password', 'PUT'],
      ['/api/sessions', 'GET'],
      ['/api/emoji', 'POST'],
      ['/api/emoji/history?sessionId=a%2Fb', 'GET'],
      ['/api/emoji/statistics?sessionId=a%2Fb', 'GET'],
    ]);
    expect(
      calls.slice(0, 2).every((c) => !(c.init.headers as Record<string, string>).Authorization),
    ).toBe(true);
    expect(
      calls
        .slice(2)
        .every((c) => (c.init.headers as Record<string, string>).Authorization === 'Bearer tok'),
    ).toBe(true);
    expect(JSON.parse(calls[0].init.body as string)).toEqual({
      username: 'alice',
      password: 'sensitive',
    });
    expect(JSON.parse(calls[1].init.body as string)).toEqual({
      username: 'alice',
      password: 'sensitive',
      email: 'a@b.test',
      role: 'STUDENT',
    });
    expect(JSON.parse(calls[4].init.body as string)).toEqual({
      oldPassword: 'oldsecret',
      newPassword: 'newsecret',
    });
    expect(JSON.parse(calls[6].init.body as string)).toEqual({
      sessionId: 'a/b',
      emotion: 'HAPPY',
    });
  });
  it.each([401, 403, 409, 422, 501, 503, 200])(
    'rejects error envelope with HTTP %i without leaking secrets',
    async (status) => {
      const repo = createApiRepository({
        fetcher: (async () => response(null, 'FAIL', status)) as typeof fetch,
      });
      const error = await repo
        .login({ username: 'alice', password: 'secret password stack' })
        .catch((e) => e);
      expect(error).toBeInstanceOf(ClientError);
      expect(error.status).toBe(status);
      expect(error.code).toBe('FAIL');
      expect(error.message).not.toContain('secret');
    },
  );
  it('rejects non-JSON, paginated history, malformed statistics and timestamps without timezone', async () => {
    const invalid = (data: unknown) =>
      createApiRepository({ fetcher: (async () => response(data)) as typeof fetch });
    await expect(
      createApiRepository({
        fetcher: (async () => new Response('<html>')) as typeof fetch,
      }).sessions('t'),
    ).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    await expect(invalid({ items: [] }).history('t')).rejects.toMatchObject({
      code: 'INVALID_RESPONSE',
    });
    await expect(invalid({ total: 1, distribution }).statistics('t', 's')).rejects.toMatchObject({
      code: 'INVALID_RESPONSE',
    });
    await expect(
      invalid({ total: 0, distribution: {} }).statistics('t', 's'),
    ).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    await expect(
      invalid([
        {
          id: 's',
          courseId: 'c',
          courseName: 'course',
          teacherName: 'teacher',
          className: 'class',
          room: 'room',
          startsAt: '2026-01-01T00:00:00',
          endsAt: '2026-01-02T00:00:00Z',
          scheduledUserIds: [],
        },
      ]).sessions('t'),
    ).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });
  it('distinguishes abort, timeout and network errors', async () => {
    const hanging = ((_: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_, reject) => {
        const signal = init!.signal!;
        if (signal.aborted) reject(new Error('aborted'));
        else signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
      })) as typeof fetch;
    const controller = new AbortController();
    controller.abort();
    await expect(
      createApiRepository({ fetcher: hanging }).sessions('t', controller.signal),
    ).rejects.toMatchObject({ code: 'ABORTED' });
    await expect(
      createApiRepository({ fetcher: hanging, timeoutMs: 5 }).sessions('t'),
    ).rejects.toMatchObject({ code: 'TIMEOUT' });
    await expect(
      createApiRepository({
        fetcher: (async () => {
          throw new Error('private');
        }) as typeof fetch,
      }).sessions('t'),
    ).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      message: expect.not.stringContaining('private'),
    });
  });
});

describe('demo boundary coverage', () => {
  const credentials = { username: 'student-a', password: 'classroom-demo-2026' };
  it('rejects admin and duplicate accounts, and disables teacher applicants', async () => {
    const storage = memory(),
      repo = createDemoRepository({ storage });
    await expect(
      repo.register({
        username: 'admin-test',
        email: 'admin@test.example',
        password: 'password123',
        role: 'ADMIN' as never,
      }),
    ).rejects.toMatchObject({ status: 422 });
    await expect(
      repo.register({
        username: 'STUDENT-A',
        email: 'new@test.example',
        password: 'password123',
        role: 'STUDENT',
      }),
    ).rejects.toMatchObject({ status: 409 });
    await expect(
      repo.register({
        username: 'new-user',
        email: 'STUDENT-A@DEMO.INVALID',
        password: 'password123',
        role: 'STUDENT',
      }),
    ).rejects.toMatchObject({ status: 409 });
    await repo.register({
      username: 'teacher-new',
      email: 'teacher-new@test.example',
      password: 'password123',
      role: 'TEACHER',
    });
    await expect(
      repo.login({ username: 'teacher-new', password: 'password123' }),
    ).rejects.toMatchObject({ status: 403 });
    expect(storage.getItem('mood-client-demo-v2')).not.toContain('password123');
  });
  it('expires tokens and denies unassigned and teacher submissions', async () => {
    let clock = 1700000000000;
    const repo = createDemoRepository({ storage: memory(), now: () => clock });
    const a = await repo.login(credentials);
    const teacher = await repo.login({ username: 'teacher-b', password: credentials.password });
    const onlyTeacher = (await repo.sessions(teacher.token))[0];
    await expect(repo.submit(a.token, onlyTeacher.id, 'HAPPY')).rejects.toMatchObject({
      status: 403,
    });
    await expect(repo.submit(teacher.token, onlyTeacher.id, 'HAPPY')).rejects.toMatchObject({
      status: 403,
    });
    clock += 8 * 3600000;
    await expect(repo.me(a.token)).rejects.toMatchObject({ status: 401 });
  });
  it('does not persist a cancelled write', async () => {
    const storage = memory(),
      repo = createDemoRepository({ storage, delayMs: 20 });
    const a = await repo.login(credentials);
    const session = (await repo.sessions(a.token))[0];
    const before = storage.getItem('mood-client-demo-v2');
    const controller = new AbortController();
    const pending = repo.submit(a.token, session.id, 'HAPPY', controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ code: 'ABORTED' });
    expect(storage.getItem('mood-client-demo-v2')).toBe(before);
  });
  it('does not overwrite corrupted data and reports unavailable storage', async () => {
    const storage = memory();
    storage.setItem('mood-client-demo-v2', '{broken');
    const repo = createDemoRepository({ storage });
    await expect(repo.login(credentials)).rejects.toMatchObject({ code: 'STORAGE_CORRUPT' });
    expect(storage.getItem('mood-client-demo-v2')).toBe('{broken');
    const unavailable = memory();
    unavailable.setItem = () => {
      throw new Error('quota');
    };
    await expect(
      createDemoRepository({ storage: unavailable }).login(credentials),
    ).rejects.toMatchObject({ code: 'STORAGE_ERROR' });
  });
  it('revokes all user tokens on password change and current token on logout', async () => {
    const repo = createDemoRepository({ storage: memory() });
    const a = await repo.login(credentials),
      b = await repo.login(credentials);
    await repo.changePassword(a.token, {
      oldPassword: credentials.password,
      newPassword: 'different-password',
    });
    await expect(repo.me(a.token)).rejects.toMatchObject({ status: 401 });
    await expect(repo.me(b.token)).rejects.toMatchObject({ status: 401 });
    const fresh = await repo.login({
      username: credentials.username,
      password: 'different-password',
    });
    await repo.logout(fresh.token);
    await expect(repo.me(fresh.token)).rejects.toMatchObject({ status: 401 });
  });
});
