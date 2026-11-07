import { useRef, useState } from 'react';
import type { AdminRegistrationRequest } from '@mood/contracts';
import { adminRegistrationRepository } from '../repositories/adminRegistrationRepository';

export function useAdminRegistration() {
  const pending = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const register = async (body: AdminRegistrationRequest): Promise<boolean> => {
    if (pending.current) return false;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      await adminRegistrationRepository.register(body);
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '注册失败，请稍后重试。');
      return false;
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  return { register, busy, error, reset: () => setError('') };
}
