import { useCallback, useEffect, useState } from 'react';
import type { WorkspaceData } from '@mood/contracts';
import { workspaceRepository } from '../repositories/workspaceRepository';

export function useWorkspace() {
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setData(await workspaceRepository.load());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '数据加载失败');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
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
  return { data, error, loading, reload: load, schedule };
}
