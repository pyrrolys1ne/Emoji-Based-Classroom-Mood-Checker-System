import type { ApiResponse, AuthSession } from '@mood/contracts';

export const dataMode = import.meta.env.VITE_DATA_MODE ?? 'demo';
export const isDemo = dataMode === 'demo';
export const isIntegration = dataMode === 'integration';
export const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '');
const key = `mood-auth-${dataMode}`;

export function cachedAuth(): AuthSession | null {
  try {
    const data = JSON.parse(sessionStorage.getItem(key) ?? 'null');
    return data?.token && data?.user?.id ? data : null;
  } catch {
    return null;
  }
}

export function saveAuth(session: AuthSession | null) {
  if (session) sessionStorage.setItem(key, JSON.stringify(session));
  else sessionStorage.removeItem(key);
}

async function fetchResponse(
  path: string,
  init: RequestInit = {},
  timeoutMs = 10000,
): Promise<Response> {
  const token = cachedAuth()?.token;
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    signal: init.signal
      ? AbortSignal.any([init.signal, AbortSignal.timeout(timeoutMs)])
      : AbortSignal.timeout(timeoutMs),
    headers: {
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  const forbidden =
    response.status === 403
      ? await response
          .clone()
          .json()
          .catch(() => null)
      : null;
  if (
    cachedAuth()?.token === token &&
    !path.startsWith('/auth/login') &&
    (response.status === 401 ||
      ['ACCOUNT_DISABLED', 'TEACHER_APPROVAL_REQUIRED'].includes(forbidden?.code))
  ) {
    saveAuth(null);
    window.dispatchEvent(new Event('mood:unauthorized'));
  }
  return response;
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = 10000,
): Promise<T> {
  const response = await fetchResponse(path, init, timeoutMs);
  const body = (await response.json().catch(() => null)) as ApiResponse<T> | null;
  if (!response.ok || !body || body.code !== 'OK')
    throw new Error(body?.message ?? `请求失败（HTTP ${response.status}）`);
  return body.data;
}

export async function requestCsv(path: string, signal?: AbortSignal): Promise<Blob> {
  const response = await fetchResponse(path, { signal }, 30000);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.message ?? `导出失败（HTTP ${response.status}）`);
  }
  if (response.headers.get('Content-Type')?.split(';')[0].trim() !== 'text/csv')
    throw new Error('服务返回的 CSV 格式无效。');
  return response.blob();
}
