import type { AdminInvitationResponse, AdminRegistrationRequest } from '@mood/contracts';
import { dataMode, request } from './http';

export const adminRegistrationEnabled = dataMode === 'api';

export const adminRegistrationRepository = {
  async register(body: AdminRegistrationRequest): Promise<void> {
    if (!adminRegistrationEnabled) throw new Error('当前环境不支持管理员注册。');
    await request('/auth/admin-register', { method: 'POST', body: JSON.stringify(body) });
  },
  async invite(expiresInHours: number): Promise<AdminInvitationResponse> {
    if (!adminRegistrationEnabled) throw new Error('当前环境不支持生成邀请码。');
    return request('/admin/invitations', {
      method: 'POST',
      body: JSON.stringify({ expiresInHours }),
    });
  },
};
