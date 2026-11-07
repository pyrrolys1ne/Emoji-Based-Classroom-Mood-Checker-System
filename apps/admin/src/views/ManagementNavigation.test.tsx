// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
const state = vi.hoisted(() => ({ role: 'TEACHER', courses: vi.fn(), applications: vi.fn() }));
vi.mock('../controllers/useAuth', () => ({
  useAuth: () => ({
    restoring: false,
    user: { id: 'u', username: 'user', role: state.role, status: 'ACTIVE' },
    logout: vi.fn(),
  }),
}));
vi.mock('../controllers/useWorkspace', () => ({
  useWorkspace: () => ({
    data: { users: [], sessions: [], records: [] },
    loading: false,
    error: '',
    reload: vi.fn(),
    schedule: vi.fn(),
    connection: 'live',
    lastUpdated: null,
  }),
}));
vi.mock('../repositories/managementRepository', () => ({
  canManage: true,
  managementNotice: '正式 API',
  managementRepository: { courses: state.courses, applications: state.applications },
}));
import { App } from './App';
afterEach(() => {
  cleanup();
  state.courses.mockReset();
  state.applications.mockReset();
});
it.each(['#teachers', '#academic'])(
  'hides privileged navigation and rejects teacher hash entry %s',
  async (hash) => {
    state.role = 'TEACHER';
    window.location.hash = hash;
    render(<App />);
    await waitFor(() => expect(window.location.hash).toBe('#dashboard'));
    expect(screen.queryByRole('button', { name: '教师审批' })).toBeNull();
    expect(screen.queryByRole('button', { name: '课程课堂' })).toBeNull();
    expect(state.courses).not.toHaveBeenCalled();
    expect(state.applications).not.toHaveBeenCalled();
  },
);
it('makes the new navigation and pending approvals accessible to administrators', async () => {
  state.role = 'ADMIN';
  state.applications.mockResolvedValue([]);
  window.location.hash = '#teachers';
  render(<App />);
  expect(screen.getByRole('button', { name: '教师审批' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '课程课堂' })).toBeTruthy();
  await screen.findByText('暂无符合条件的申请');
  expect(state.applications).toHaveBeenCalled();
});
