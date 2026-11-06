import { afterEach, expect, it, vi } from 'vitest';
import { emotions } from '@mood/contracts';
import { statisticsQuery, statisticsRepository, validStatistics } from './statisticsRepository';

const valid = () => ({
  total: 2,
  source: 'MANUAL',
  distribution: Object.fromEntries(
    Object.keys(emotions).map((key) => [key, key === 'HAPPY' ? 2 : 0]),
  ),
  timeline: [{ startsAt: '2026-11-01T09:00:00Z', endsAt: '2026-11-01T09:01:00Z', total: 2 }],
  groups: [
    { courseId: 'course', courseName: '课程', className: '班级', total: 2, manual: 2, ai: 0 },
  ],
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it('serializes classroom, source, emotion, Chinese class and timezone filters exactly', () => {
  const query = statisticsQuery({
    sessionId: 'a/b',
    source: 'AI',
    emotion: 'HAPPY',
    class: '中文班',
    from: '2026-11-01T17:00:00+08:00',
    course: undefined,
  });
  expect(Object.fromEntries(new URLSearchParams(query))).toEqual({
    sessionId: 'a/b',
    source: 'AI',
    emotion: 'HAPPY',
    class: '中文班',
    from: '2026-11-01T17:00:00+08:00',
  });
});

it.each([
  { total: 3 },
  { source: 'unknown' },
  { distribution: {} },
  { timeline: [] },
  { groups: [] },
  {
    groups: [{ courseId: 'c', courseName: '课程', className: '班级', total: 2, manual: 1, ai: 0 }],
  },
  { timeline: [{ startsAt: '2026-11-01T09:00:00', endsAt: '2026-11-01T09:01:00Z', total: 2 }] },
  {
    timeline: [
      { startsAt: '2026-11-01T09:00:00Z', endsAt: '2026-11-01T09:01:00Z', total: 1 },
      { startsAt: '2026-11-01T08:00:00Z', endsAt: '2026-11-01T09:00:00Z', total: 1 },
    ],
  },
])('rejects inconsistent full statistics: %j', (change) => {
  expect(validStatistics({ ...valid(), ...change })).toBe(false);
});

it('accepts complete counters and empty results', () => {
  expect(validStatistics(valid())).toBe(true);
  expect(
    validStatistics({
      total: 0,
      source: 'AI',
      timeline: [],
      groups: [],
      distribution: Object.fromEntries(Object.keys(emotions).map((key) => [key, 0])),
    }),
  ).toBe(true);
});

function authentication() {
  vi.stubGlobal('sessionStorage', {
    getItem: () => JSON.stringify({ token: 'synthetic-token', user: { id: 'admin' } }),
    removeItem: vi.fn(),
  });
  const dispatch = vi.fn();
  vi.stubGlobal('window', { dispatchEvent: dispatch });
  return dispatch;
}

it('downloads only a real CSV response and carries all filters with authentication', async () => {
  authentication();
  const fetcher = vi.fn(
    async () =>
      new Response('\ufeff"记录编号"\r\n"one"\r\n', {
        headers: { 'Content-Type': 'text/csv; charset=utf-8' },
      }),
  );
  vi.stubGlobal('fetch', fetcher);
  const blob = await statisticsRepository.exportCsv({
    sessionId: 'classroom',
    emotion: 'SAD',
    source: 'AI',
    format: 'csv',
  });
  const [url, request] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  const query = new URL(url, 'http://localhost').searchParams;
  expect(query.getAll('format')).toEqual(['csv']);
  expect(query.get('source')).toBe('AI');
  expect(query.get('emotion')).toBe('SAD');
  expect(query.get('sessionId')).toBe('classroom');
  expect((request.headers as Record<string, string>).Authorization).toBe('Bearer synthetic-token');
  expect(await blob.text()).toContain('"one"');
});

it('rejects JSON placeholders instead of creating a misleading CSV download', async () => {
  authentication();
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify({ code: 'OK', data: null }), {
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  );
  await expect(statisticsRepository.exportCsv({})).rejects.toThrow('CSV 格式无效');
});

it('revokes the local session on an unauthorized CSV response', async () => {
  const dispatch = authentication();
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify({ code: 'UNAUTHENTICATED', message: '身份失效' }), {
          status: 401,
        }),
    ),
  );
  await expect(statisticsRepository.exportCsv({})).rejects.toThrow('身份失效');
  expect(dispatch).toHaveBeenCalledOnce();
});

it.each(['ACCOUNT_DISABLED', 'TEACHER_APPROVAL_REQUIRED'])(
  '账号被撤销时清理旧数据：%s',
  async (code) => {
    const dispatch = authentication();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () => new Response(JSON.stringify({ code, message: '访问被撤销' }), { status: 403 }),
      ),
    );
    await expect(statisticsRepository.exportCsv({})).rejects.toThrow('访问被撤销');
    expect(dispatch).toHaveBeenCalledOnce();
  },
);

it('旧会话的迟到拒绝不能清除刚登录的新会话', async () => {
  const dispatch = authentication();
  let release!: (response: Response) => void;
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    ),
  );
  const pending = statisticsRepository.exportCsv({});
  vi.stubGlobal('sessionStorage', {
    getItem: () => JSON.stringify({ token: 'new-session', user: { id: 'other' } }),
    removeItem: vi.fn(),
  });
  release(new Response(JSON.stringify({ code: 'UNAUTHENTICATED' }), { status: 401 }));
  await expect(pending).rejects.toThrow();
  expect(dispatch).not.toHaveBeenCalled();
});

it('validates source and counters before presenting a server aggregate', async () => {
  authentication();
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ code: 'OK', data: valid() }))),
  );
  expect((await statisticsRepository.statistics({})).total).toBe(2);
  await expect(statisticsRepository.statistics({ source: 'AI' })).rejects.toThrow('来源无效');
});
