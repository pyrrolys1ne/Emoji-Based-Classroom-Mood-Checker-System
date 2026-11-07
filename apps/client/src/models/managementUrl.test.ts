import { expect, it } from 'vitest';
import { managementUrl } from './managementUrl';

it('uses the browser host for local and LAN management links', () => {
  expect(managementUrl('http://127.0.0.1:5174/history')).toBe('http://127.0.0.1:5173/');
  expect(managementUrl('http://192.168.1.20:5174/?x=1#teacher', '')).toBe(
    'http://192.168.1.20:5173/',
  );
  expect(managementUrl('http://[::1]:5174/')).toBe('http://[::1]:5173/');
});
it('accepts an explicit entrance and rejects credentialed or unsafe links', () => {
  expect(managementUrl('http://192.168.1.20:5174/', 'http://192.168.1.20:9000')).toBe(
    'http://192.168.1.20:9000/',
  );
  expect(managementUrl('http://127.0.0.1:5174/', 'javascript:alert(1)')).toBe('');
  expect(managementUrl('http://127.0.0.1:5174/', 'http://user:pass@example.test/')).toBe('');
});
