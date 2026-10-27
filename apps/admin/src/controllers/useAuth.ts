import { useEffect, useState } from 'react';
import type { AuthSession, User } from '@mood/contracts';
import { cachedAuth, isDemo, request, saveAuth } from '../repositories/http';

const demoUser: User = {
  id: 'admin-1',
  username: '演示管理员',
  email: 'admin@example.edu',
  role: 'ADMIN',
  status: 'ACTIVE',
};

export function useAuth() {
  const [user, setUser] = useState<User | null>(isDemo ? demoUser : null);
  const [restoring, setRestoring] = useState(!isDemo && Boolean(cachedAuth()));
  useEffect(() => {
    const clear = () => setUser(null);
    window.addEventListener('mood:unauthorized', clear);
    let active = true;
    if (!isDemo && cachedAuth()) {
      request<User>('/users/me')
        .then((value) => {
          if (active && (value.role === 'ADMIN' || value.role === 'TEACHER')) setUser(value);
        })
        .catch(() => {
          saveAuth(null);
        })
        .finally(() => {
          if (active) setRestoring(false);
        });
    }
    return () => {
      active = false;
      window.removeEventListener('mood:unauthorized', clear);
    };
  }, []);
  const login = async (username: string, password: string) => {
    const session = await request<AuthSession>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    if (!session.token || !['ADMIN', 'TEACHER'].includes(session.user.role))
      throw new Error('该账号无管理端访问权限');
    saveAuth(session);
    setUser(session.user);
  };
  const logout = async () => {
    try {
      await request('/auth/logout', { method: 'POST' });
    } finally {
      saveAuth(null);
      setUser(null);
    }
  };
  return { user, restoring, login, logout };
}
