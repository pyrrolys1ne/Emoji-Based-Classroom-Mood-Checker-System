import type { AuthSession } from '@mood/contracts';
import type { DataMode } from '../models/client';

export function sessionStore(mode: DataMode, storage?: Storage) {
  const key = `mood-client-auth-${mode}`;
  const target = () => storage ?? window.sessionStorage;
  return {
    read(): AuthSession | null {
      try {
        const value = JSON.parse(target().getItem(key) ?? 'null') as AuthSession | null;
        if (
          !value ||
          typeof value.token !== 'string' ||
          !value.token ||
          typeof value.user?.id !== 'string' ||
          typeof value.user.username !== 'string' ||
          typeof value.user.email !== 'string' ||
          value.user.status !== 'ACTIVE' ||
          !['STUDENT', 'TEACHER'].includes(value.user.role)
        )
          return null;
        return value;
      } catch {
        return null;
      }
    },
    write(value: AuthSession | null): boolean {
      try {
        if (value) target().setItem(key, JSON.stringify(value));
        else target().removeItem(key);
        return true;
      } catch {
        return false;
      }
    },
  };
}
