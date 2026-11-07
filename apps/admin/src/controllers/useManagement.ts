import { useCallback, useEffect, useRef, useState } from 'react';
import { canManage } from '../repositories/managementRepository';

export function useManagementList<T>(loader: (signal?: AbortSignal) => Promise<T[]>) {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(canManage);
  const [error, setError] = useState('');
  const abort = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    if (!canManage) return;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setLoading(true);
    setError('');
    try {
      const next = await loader(controller.signal);
      if (!controller.signal.aborted) setItems(next);
    } catch (reason) {
      if (!controller.signal.aborted)
        setError(reason instanceof Error ? reason.message : '加载失败');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [loader]);
  useEffect(() => {
    void refresh();
    return () => abort.current?.abort();
  }, [refresh]);
  return { items, loading, error, refresh };
}

export function useManagementAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const locked = useRef(false);
  const run = async (action: () => Promise<unknown>) => {
    if (locked.current) return false;
    locked.current = true;
    setBusy(true);
    setError('');
    try {
      await action();
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '操作失败，请刷新核对结果');
      return false;
    } finally {
      locked.current = false;
      setBusy(false);
    }
  };
  return { busy, error, run };
}
