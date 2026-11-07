import { beforeEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ demo: false, integration: false, request: vi.fn() }));
vi.mock('./http', () => ({
  get isDemo() {
    return state.demo;
  },
  get isIntegration() {
    return state.integration;
  },
  request: state.request,
}));
beforeEach(() => {
  vi.resetModules();
  state.request.mockReset();
});
it.each(['demo', 'integration'] as const)(
  'refuses management calls in %s mode without touching the API',
  async (mode) => {
    state.demo = mode === 'demo';
    state.integration = mode === 'integration';
    const { managementRepository: repo, canManage } = await import('./managementRepository');
    expect(canManage).toBe(false);
    await expect(repo.courses()).rejects.toThrow('正式后端');
    await expect(repo.applications()).rejects.toThrow('正式后端');
    await expect(repo.saveStudent('s', { realName: '姓名' })).rejects.toThrow('正式后端');
    await expect(repo.review('a', { decision: 'APPROVED' })).rejects.toThrow('正式后端');
    await expect(repo.saveCourse({ name: '课', teacherId: 't' })).rejects.toThrow('正式后端');
    expect(state.request).not.toHaveBeenCalled();
  },
);
