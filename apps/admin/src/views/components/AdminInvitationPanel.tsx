import { useState } from 'react';
import type { AdminInvitationResponse } from '@mood/contracts';
import {
  adminRegistrationEnabled,
  adminRegistrationRepository,
} from '../../repositories/adminRegistrationRepository';

export function AdminInvitationPanel() {
  const [hours, setHours] = useState(24);
  const [invitation, setInvitation] = useState<AdminInvitationResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!adminRegistrationEnabled) return null;
  const generate = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    setInvitation(null);
    try {
      setInvitation(await adminRegistrationRepository.invite(hours));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '邀请码生成失败。');
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="admin-invitation" aria-label="邀请管理员">
      <h3>邀请管理员</h3>
      <p>邀请码可注册一个新的管理员账号，请仅交给获授权的人员。</p>
      <div className="filters">
        <label>
          邀请码有效期
          <select
            value={hours}
            onChange={(event) => setHours(Number(event.target.value))}
            disabled={busy}
          >
            <option value={1}>1 小时</option>
            <option value={24}>24 小时</option>
            <option value={72}>3 天</option>
            <option value={168}>7 天</option>
          </select>
        </label>
        <button
          className="button secondary"
          type="button"
          disabled={busy}
          onClick={() => void generate()}
        >
          {busy ? '正在生成…' : '生成管理员邀请码'}
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {invitation && (
        <div role="status">
          <label>
            一次性邀请码
            <input readOnly autoComplete="off" value={invitation.code} />
          </label>
          <p>
            有效至 {new Date(invitation.expiresAt).toLocaleString('zh-CN')}，注册成功后立即失效。
          </p>
          <button className="text-button" type="button" onClick={() => setInvitation(null)}>
            隐藏邀请码
          </button>
        </div>
      )}
    </section>
  );
}
