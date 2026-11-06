import { apiBase, cachedAuth, request, saveAuth } from './http';
import type { RealtimeSnapshot, User } from '@mood/contracts';

export type ConnectionState = 'connecting' | 'live' | 'polling' | 'offline';

export function realtimeUrl(
  api: string,
  origin: string,
  ticket: string,
  endpoint = '/ws/dashboard',
) {
  const url = new URL(endpoint, new URL(api, origin));
  if (url.protocol === 'https:') url.protocol = 'wss:';
  else if (url.protocol === 'http:') url.protocol = 'ws:';
  if (!['ws:', 'wss:'].includes(url.protocol) || url.username || url.password)
    throw new Error('实时通道地址无效。');
  url.search = '';
  url.hash = '';
  url.searchParams.set('ticket', ticket);
  return url;
}

export function validSnapshot(value: unknown): value is RealtimeSnapshot {
  if (!value || typeof value !== 'object') return false;
  const data = value as RealtimeSnapshot;
  return (
    data.type === 'snapshot' &&
    Number.isSafeInteger(data.total) &&
    data.total >= 0 &&
    (data.latestId === null || (typeof data.latestId === 'string' && data.latestId.length > 0)) &&
    (data.version === undefined ||
      (typeof data.version === 'string' && /^[a-f0-9]{64}$/.test(data.version)))
  );
}

export function subscribeRealtime(
  refresh: () => Promise<void>,
  state: (value: ConnectionState) => void,
) {
  let stopped = false;
  let socket: WebSocket | null = null;
  let retry: ReturnType<typeof setTimeout>;
  let attempts = 0;
  let fingerprint = '';
  const abort = new AbortController();
  const connect = async () => {
    if (stopped) return;
    state('connecting');
    try {
      const { ticket } = await request<{ ticket: string }>('/auth/ws-ticket', {
        method: 'POST',
        signal: abort.signal,
      });
      if (stopped) return;
      const wsUrl = realtimeUrl(apiBase, location.origin, ticket, import.meta.env.VITE_WS_URL);
      const nextSocket = new WebSocket(wsUrl);
      socket = nextSocket;
      const handshakeTimeout = setTimeout(() => nextSocket.close(), 10000);
      nextSocket.onopen = () => {
        clearTimeout(handshakeTimeout);
        attempts = 0;
        state('live');
      };
      nextSocket.onmessage = (event) => {
        try {
          const snapshot = JSON.parse(event.data);
          if (!validSnapshot(snapshot)) return;
          const next = JSON.stringify([snapshot.total, snapshot.latestId, snapshot.version]);
          if (next !== fingerprint) {
            fingerprint = next;
            void refresh();
          }
        } catch {
          /* 非法事件不影响轮询兜底。 */
        }
      };
      nextSocket.onclose = (event) => {
        clearTimeout(handshakeTimeout);
        if (event.code === 1008 && !stopped) {
          void request<User>('/users/me', { signal: abort.signal })
            .then((user) => {
              if (!stopped && cachedAuth()?.user.role !== user.role) {
                saveAuth(null);
                window.dispatchEvent(new Event('mood:unauthorized'));
              }
            })
            .catch(() => {});
        }
        retryConnect();
      };
      nextSocket.onerror = () => nextSocket.close();
    } catch {
      retryConnect();
    }
  };
  const retryConnect = () => {
    if (stopped) return;
    state('polling');
    retry = setTimeout(() => void connect(), Math.min(30000, 1000 * 2 ** Math.min(attempts++, 5)));
  };
  const poll = setInterval(() => {
    if (document.visibilityState === 'visible') void refresh();
  }, 5000);
  void connect();
  return () => {
    stopped = true;
    abort.abort();
    clearInterval(poll);
    clearTimeout(retry);
    socket?.close();
  };
}
