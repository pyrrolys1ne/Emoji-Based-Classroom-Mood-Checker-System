import { afterEach, expect, it, vi } from 'vitest';
import { realtimeUrl, subscribeRealtime, validSnapshot } from './realtime';

it('保留显式配置的 wss 加密通道，不降级为 ws', () => {
  const url = realtimeUrl(
    '/api',
    'https://mood.example',
    'one-time-ticket',
    'wss://api.example/ws/dashboard',
  );
  expect(url.protocol).toBe('wss:');
  expect(url.host).toBe('api.example');
  expect(url.searchParams.get('ticket')).toBe('one-time-ticket');
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it('通道地址仅携带一次性票据，不保留配置中的旧访问参数', () => {
  expect(
    realtimeUrl('/api', 'https://mood.example', 'ticket', '/ws/dashboard?token=private').search,
  ).toBe('?ticket=ticket');
  expect(() =>
    realtimeUrl('/api', 'https://mood.example', 'ticket', 'wss://user:private@api.example/ws'),
  ).toThrow('无效');
});

it.each([
  null,
  {},
  { type: 'snapshot', total: -1, latestId: null },
  { type: 'snapshot', total: 0, latestId: null, version: 'private' },
])('拒绝无效快照 %j', (value) => {
  expect(validSnapshot(value)).toBe(false);
});

it('元数据版本变化会刷新，断线重连换票据，退出后停止重连和轮询', async () => {
  vi.useFakeTimers();
  const sockets: any[] = [];
  class Socket {
    onopen?: () => void;
    onmessage?: (event: { data: string }) => void;
    onclose?: (event: { code: number }) => void;
    close = vi.fn(() => this.onclose?.({ code: 1000 }));
    constructor(public url: string) {
      sockets.push(this);
    }
  }
  const fetcher = vi.fn(
    async () =>
      new Response(JSON.stringify({ code: 'OK', data: { ticket: `ticket-${sockets.length}` } })),
  );
  vi.stubGlobal('fetch', fetcher);
  vi.stubGlobal('WebSocket', Socket);
  vi.stubGlobal('location', { origin: 'http://127.0.0.1:5173' });
  vi.stubGlobal('document', { visibilityState: 'visible' });
  vi.stubGlobal('sessionStorage', { getItem: () => null });
  const refresh = vi.fn(async () => {}),
    state = vi.fn();
  const stop = subscribeRealtime(refresh, state);
  await vi.advanceTimersByTimeAsync(0);
  sockets[0].onopen();
  const send = (version: string) =>
    sockets[0].onmessage({
      data: JSON.stringify({ type: 'snapshot', total: 0, latestId: null, version }),
    });
  send('a'.repeat(64));
  send('a'.repeat(64));
  send('b'.repeat(64));
  expect(refresh).toHaveBeenCalledTimes(2);
  sockets[0].onclose({ code: 1006 });
  await vi.advanceTimersByTimeAsync(1000);
  expect(sockets).toHaveLength(2);
  expect(sockets[0].url).not.toBe(sockets[1].url);
  sockets[1].onopen();
  await vi.advanceTimersByTimeAsync(4000);
  expect(refresh).toHaveBeenCalledTimes(3);
  stop();
  await vi.advanceTimersByTimeAsync(60000);
  expect(refresh).toHaveBeenCalledTimes(3);
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it('按 API 域名选择通道，HTTPS 自动使用 wss', () => {
  expect(realtimeUrl('https://api.example/api', 'http://127.0.0.1', 't').href).toBe(
    'wss://api.example/ws/dashboard?ticket=t',
  );
  expect(realtimeUrl('/api', 'http://127.0.0.1:5175', 't').protocol).toBe('ws:');
});

it.each(['', '   '])('空的构建配置 %j 使用默认实时路径', (endpoint) => {
  expect(realtimeUrl('/api', 'https://mood.example', 't', endpoint).href).toBe(
    'wss://mood.example/ws/dashboard?ticket=t',
  );
});
