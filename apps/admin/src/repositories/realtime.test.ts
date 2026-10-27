import { expect, it } from 'vitest';
import { realtimeUrl } from './realtime';

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

it('按 API 域名选择通道，HTTPS 自动使用 wss', () => {
  expect(realtimeUrl('https://api.example/api', 'http://127.0.0.1', 't').href).toBe(
    'wss://api.example/ws/dashboard?ticket=t',
  );
  expect(realtimeUrl('/api', 'http://127.0.0.1:5175', 't').protocol).toBe('ws:');
});
