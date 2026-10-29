import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AuthSession } from '@mood/contracts';
import {
  ClientError,
  messageOf,
  writeResultIsUnknown,
  type AuthView,
  type ClientRepository,
  type LoginInput,
  type PasswordInput,
  type RegisterInput,
} from '../models/client';
import { sessionStore } from './sessionStore';

export function useClientAuth(repository: ClientRepository, storage?: Storage) {
  const store = useMemo(() => sessionStore(repository.mode, storage), [repository.mode, storage]);
  const [session, setSession] = useState<AuthSession | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [view, setView] = useState<AuthView>('login');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [initialUsername, setInitialUsername] = useState('');
  const [passwordPending, setPasswordPending] = useState(false);
  const [passwordError, setPasswordError] = useState('');
  const version = useRef(0);
  const busy = useRef(false);
  const controller = useRef<AbortController | null>(null);

  const reset = useCallback(
    (text: string) => {
      version.current += 1;
      controller.current?.abort();
      busy.current = false;
      store.write(null);
      setSession(null);
      setPending(false);
      setPasswordPending(false);
      setPasswordError('');
      setError('');
      setView('login');
      setNotice(text);
    },
    [store],
  );

  const expire = useCallback(
    (value: unknown) => {
      if (!(value instanceof ClientError) || value.status !== 401) return false;
      reset('登录已过期，请重新登录。');
      return true;
    },
    [reset],
  );

  useEffect(() => {
    const id = ++version.current;
    const abort = new AbortController();
    controller.current = abort;
    setRestoring(true);
    setSession(null);
    const cached = store.read();
    if (!cached) {
      store.write(null);
      setRestoring(false);
      return () => {
        version.current += 1;
        abort.abort();
      };
    }
    repository
      .me(cached.token, abort.signal)
      .then((user) => {
        if (version.current !== id) return;
        if (user.status !== 'ACTIVE' || !['STUDENT', 'TEACHER'].includes(user.role))
          throw new ClientError('该账号无法使用客户端，请联系老师。', 403);
        const restored = { token: cached.token, user };
        store.write(restored);
        setSession(restored);
      })
      .catch((value: unknown) => {
        if (version.current !== id) return;
        store.write(null);
        setNotice(
          value instanceof ClientError && value.status === 401
            ? '登录已过期，请重新登录。'
            : `无法恢复登录：${messageOf(value)}`,
        );
      })
      .finally(() => {
        if (version.current === id) setRestoring(false);
      });
    return () => {
      version.current += 1;
      abort.abort();
    };
  }, [repository, store]);

  const login = async (input: LoginInput): Promise<boolean> => {
    if (busy.current) return false;
    busy.current = true;
    const id = ++version.current;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setPending(true);
    setError('');
    setNotice('');
    try {
      const result = await repository.login(input, abort.signal);
      if (id !== version.current) return false;
      if (result.user.status !== 'ACTIVE' || !['STUDENT', 'TEACHER'].includes(result.user.role))
        throw new ClientError('该账号请通过管理端登录，或联系老师确认权限。', 403);
      if (!store.write(result)) setNotice('浏览器未能保存登录状态，刷新后需要重新登录。');
      setSession(result);
      setPasswordError('');
      return true;
    } catch (value) {
      if (id === version.current) setError(messageOf(value));
      return false;
    } finally {
      if (id === version.current) {
        busy.current = false;
        setPending(false);
      }
    }
  };

  const register = async (input: RegisterInput): Promise<boolean> => {
    if (busy.current) return false;
    busy.current = true;
    const id = ++version.current;
    const abort = new AbortController();
    controller.current?.abort();
    controller.current = abort;
    setPending(true);
    setError('');
    setNotice('');
    try {
      await repository.register(input, abort.signal);
      if (id !== version.current) return false;
      setInitialUsername(input.username);
      setView('login');
      setNotice(
        input.role === 'TEACHER'
          ? '注册请求已处理，请在取得教师权限后登录。'
          : '注册成功，请登录。',
      );
      return true;
    } catch (value) {
      if (id === version.current) setError(messageOf(value));
      return false;
    } finally {
      if (id === version.current) {
        busy.current = false;
        setPending(false);
      }
    }
  };

  const logout = (unknownWrite = false) => {
    const token = session?.token;
    const suffix =
      unknownWrite || passwordPending ? ' 刚才操作的结果尚未确认，请重新登录后核实。' : '';
    reset(`已退出登录。${suffix}`);
    const id = version.current;
    if (token)
      void repository.logout(token).catch(() => {
        if (id === version.current)
          setNotice(`已在此设备退出；服务器注销尚未确认，请联系老师。${suffix}`);
      });
  };

  const changePassword = async (input: PasswordInput): Promise<boolean> => {
    if (!session || busy.current) return false;
    busy.current = true;
    const id = version.current;
    const abort = new AbortController();
    controller.current?.abort();
    controller.current = abort;
    setPasswordPending(true);
    setPasswordError('');
    try {
      await repository.changePassword(session.token, input, abort.signal);
      if (id !== version.current) return false;
      reset('密码已更新，请重新登录。');
      return true;
    } catch (value) {
      if (id === version.current && !expire(value)) {
        setPasswordError(
          writeResultIsUnknown(value)
            ? `${messageOf(value)} 密码修改结果尚未确认，请退出后尝试用新密码登录核实。`
            : messageOf(value),
        );
      }
      return false;
    } finally {
      if (id === version.current) {
        busy.current = false;
        setPasswordPending(false);
      }
    }
  };

  return {
    session,
    restoring,
    view,
    pending,
    error,
    notice,
    initialUsername,
    passwordPending,
    passwordError,
    login,
    register,
    logout,
    changePassword,
    expire,
    changeView: (next: AuthView) => {
      if (!pending) {
        setView(next);
        setError('');
        setNotice('');
      }
    },
  };
}
