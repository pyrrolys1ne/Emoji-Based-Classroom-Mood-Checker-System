import { useCallback, useEffect, useRef, useState } from 'react';
import type { WorkspaceData } from '@mood/contracts';
import { workspaceRepository, isDemo } from '../repositories/workspaceRepository';
import { subscribeRealtime, type ConnectionState } from '../repositories/realtime';

export function useWorkspace() {
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [connection, setConnection] = useState<ConnectionState>('connecting');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const busy = useRef(false);
  const mounted = useRef(true);
  const load = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const next = await workspaceRepository.load();
      if (!mounted.current) return;
      setData(next);
      setError('');
      setLastUpdated(new Date());
    } catch (reason) {
      if (mounted.current) {
        setError(reason instanceof Error ? reason.message : '数据加载失败');
      }
    } finally {
      busy.current = false;
      if (mounted.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void load();
    const unsubscribe = isDemo ? () => {} : subscribeRealtime(load, setConnection);
    return () => {
      mounted.current = false;
      unsubscribe();
    };
  }, [load]);
  const schedule = async (sessionId: string, userIds: string[]) => {
    await workspaceRepository.schedule(sessionId, userIds);
    setData(
      (current) =>
        current && {
          ...current,
          sessions: current.sessions.map((session) =>
            session.id === sessionId ? { ...session, scheduledUserIds: userIds } : session,
          ),
        },
    );
  };
  return {
    data,
    error,
    loading,
    reload: load,
    schedule,
    connection: error ? ('offline' as const) : connection,
    lastUpdated,
  };
}
