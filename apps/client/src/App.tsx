import { useMemo, useState } from 'react';
import type { AuthSession } from '@mood/contracts';
import { messageOf, type ClientRepository, type Page } from './models/client';
import { createApiRepository, createDemoRepository } from './repositories';
import { AccountView, AppShell, AuthView, HistoryView, StudentView, TeacherView } from './views';
import { useClientAuth } from './viewmodels/useClientAuth';
import { useClassroom } from './viewmodels/useClassroom';

interface AppProps {
  repository?: ClientRepository;
  storage?: Storage;
}
function safeAdminUrl(): string {
  try {
    const url = new URL(
      import.meta.env.VITE_ADMIN_URL ?? 'http://127.0.0.1:5173',
      window.location.href,
    );
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password
      ? url.href
      : '';
  } catch {
    return '';
  }
}
function Workspace({
  repository,
  session,
  auth,
}: {
  repository: ClientRepository;
  session: AuthSession;
  auth: ReturnType<typeof useClientAuth>;
}) {
  const [page, setPage] = useState<Page>(session.user.role === 'TEACHER' ? 'teacher' : 'feedback');
  const data = useClassroom(repository, session, auth.expire);
  const historyProps = {
    sessions: data.sessions,
    selectedSessionId: data.selectedSessionId,
    onSessionChange: data.selectSession,
    records: data.records,
    loading: data.sessionsLoading || data.historyLoading,
    error: data.sessionsError || data.historyError,
    onRetry: data.sessionsError ? data.retrySessions : data.retry,
  };
  return (
    <AppShell
      user={session.user}
      mode={repository.mode}
      page={page}
      onNavigate={(next) => {
        if (next === 'feedback' && !data.selectedSessionId && data.sessions[0])
          data.selectSession(data.sessions[0].id);
        setPage(next);
      }}
      onLogout={() => auth.logout(data.submitting)}
      logoutPending={false}
      navigationPending={data.submitting}
      notice={auth.notice}
      adminUrl={safeAdminUrl()}
    >
      {page === 'account' ? (
        <AccountView
          user={session.user}
          onChangePassword={auth.changePassword}
          pending={auth.passwordPending}
          error={auth.passwordError}
          notice=""
        />
      ) : session.user.role === 'TEACHER' ? (
        <TeacherView
          {...historyProps}
          statistics={data.statistics}
          statisticsLoading={data.statisticsLoading}
          statisticsError={data.statisticsError}
        />
      ) : page === 'history' ? (
        <HistoryView {...historyProps} />
      ) : (
        <StudentView
          sessions={data.sessions}
          selectedSessionId={data.selectedSessionId}
          onSessionChange={data.selectSession}
          sessionsLoading={data.sessionsLoading}
          sessionsError={data.sessionsError}
          onSessionsRetry={data.retrySessions}
          selectedEmotion={data.selectedEmotion}
          onEmotionChange={data.selectEmotion}
          onSubmit={() => void data.submit()}
          submitting={data.submitting}
          submitError={data.submitError}
          submitNotice={data.submitNotice}
          canSubmit={data.canSubmit}
          records={data.records}
          historyLoading={data.historyLoading}
          historyError={data.historyError}
          onHistoryRetry={data.retry}
        />
      )}
    </AppShell>
  );
}
function ClientApp({ repository, storage }: { repository: ClientRepository; storage?: Storage }) {
  const auth = useClientAuth(repository, storage);
  if (auth.restoring)
    return (
      <main className="restore-screen">
        <p role="status">正在恢复登录…</p>
      </main>
    );
  if (!auth.session)
    return (
      <AuthView
        view={auth.view}
        onViewChange={auth.changeView}
        onLogin={auth.login}
        onRegister={auth.register}
        pending={auth.pending}
        error={auth.error}
        notice={auth.notice}
        mode={repository.mode}
        initialUsername={auth.initialUsername}
      />
    );
  return (
    <Workspace
      key={auth.session.token}
      repository={repository}
      session={auth.session}
      auth={auth}
    />
  );
}
export function App({ repository, storage }: AppProps) {
  const resolved = useMemo(() => {
    try {
      if (repository) return { repository, error: '' };
      const mode = import.meta.env.VITE_DATA_MODE ?? 'demo';
      if (mode === 'demo') return { repository: createDemoRepository(), error: '' };
      if (mode === 'api')
        return {
          repository: createApiRepository({ baseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api' }),
          error: '',
        };
      return { repository: null, error: '请联系维护者检查页面配置。' };
    } catch (error) {
      return { repository: null, error: messageOf(error) };
    }
  }, [repository]);
  if (!resolved.repository)
    return (
      <main className="restore-screen">
        <h1>页面暂不可用</h1>
        <p role="alert">{resolved.error}</p>
      </main>
    );
  return <ClientApp repository={resolved.repository} storage={storage} />;
}
