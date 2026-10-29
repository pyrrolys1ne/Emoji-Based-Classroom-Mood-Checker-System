import { useCallback, useEffect, useRef, useState } from 'react';
import type { AuthSession, ClassSession, Emotion, EmojiRecord } from '@mood/contracts';
import {
  ClientError,
  canSubmitTo,
  messageOf,
  writeResultIsUnknown,
  type ClientRepository,
  type EmotionStatistics,
} from '../models/client';

export function useClassroom(
  repository: ClientRepository,
  session: AuthSession,
  expire: (value: unknown) => boolean,
) {
  const [sessions, setSessions] = useState<ClassSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState('');
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [sessionsError, setSessionsError] = useState('');
  const [records, setRecords] = useState<EmojiRecord[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [statistics, setStatistics] = useState<EmotionStatistics | null>(null);
  const [statisticsLoading, setStatisticsLoading] = useState(false);
  const [statisticsError, setStatisticsError] = useState('');
  const [selectedEmotion, setSelectedEmotion] = useState<Emotion | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [submitNotice, setSubmitNotice] = useState('');
  const [sessionsVersion, setSessionsVersion] = useState(0);
  const [recordsVersion, setRecordsVersion] = useState(0);
  const [now, setNow] = useState(Date.now());
  const mutation = useRef<{ controller: AbortController } | null>(null);
  const token = session.token;
  const teacher = session.user.role === 'TEACHER';

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    let active = true;
    setSessionsLoading(true);
    setSessionsError('');
    setSessions([]);
    repository
      .sessions(token, abort.signal)
      .then((rows) => {
        if (!active) return;
        setSessions(rows);
        setSelectedSessionId((current) =>
          rows.some((item) => item.id === current)
            ? current
            : ((rows.find((item) => canSubmitTo(item)) ?? rows[0])?.id ?? ''),
        );
      })
      .catch((error: unknown) => {
        if (active && !expire(error)) setSessionsError(messageOf(error));
      })
      .finally(() => {
        if (active) setSessionsLoading(false);
      });
    return () => {
      active = false;
      abort.abort();
    };
  }, [repository, token, sessionsVersion, expire]);

  useEffect(() => {
    const abort = new AbortController();
    let active = true;
    setRecords([]);
    setHistoryError('');
    setStatistics(null);
    setStatisticsError('');
    if (sessionsLoading || sessionsError || (teacher && !selectedSessionId)) {
      setHistoryLoading(false);
      setStatisticsLoading(false);
      return () => {
        active = false;
        abort.abort();
      };
    }
    setHistoryLoading(true);
    repository
      .history(token, selectedSessionId || undefined, abort.signal)
      .then((rows) => {
        if (
          (!teacher &&
            rows.some((row) => row.userId !== session.user.id || row.source !== 'MANUAL')) ||
          (selectedSessionId && rows.some((row) => row.sessionId !== selectedSessionId))
        ) {
          throw new ClientError(
            '记录范围与当前账号或课堂不符，已停止展示。',
            403,
            'SCOPE_MISMATCH',
          );
        }
        if (active)
          setRecords([...rows].sort((a, b) => Date.parse(b.recordedAt) - Date.parse(a.recordedAt)));
      })
      .catch((error: unknown) => {
        if (active && !expire(error)) setHistoryError(messageOf(error));
      })
      .finally(() => {
        if (active) setHistoryLoading(false);
      });
    if (teacher) {
      setStatisticsLoading(true);
      repository
        .statistics(token, selectedSessionId, abort.signal)
        .then((value) => {
          if (active) setStatistics(value);
        })
        .catch((error: unknown) => {
          if (active && !expire(error)) setStatisticsError(messageOf(error));
        })
        .finally(() => {
          if (active) setStatisticsLoading(false);
        });
    } else setStatisticsLoading(false);
    return () => {
      active = false;
      abort.abort();
    };
  }, [
    repository,
    token,
    selectedSessionId,
    recordsVersion,
    teacher,
    sessionsLoading,
    sessionsError,
    expire,
  ]);

  useEffect(() => {
    setSelectedEmotion(null);
    setSubmitError('');
    setSubmitNotice('');
    setSubmitting(false);
    return () => {
      mutation.current?.controller.abort();
      mutation.current = null;
    };
  }, [token, selectedSessionId]);

  const selectedSession = sessions.find((item) => item.id === selectedSessionId) ?? null;
  const canSubmit =
    session.user.role === 'STUDENT' &&
    !sessionsLoading &&
    !sessionsError &&
    canSubmitTo(selectedSession, now);
  const retry = useCallback(() => setRecordsVersion((value) => value + 1), []);
  const submit = async () => {
    if (mutation.current || !canSubmit || !selectedEmotion || !selectedSession) return;
    const current = { controller: new AbortController() };
    mutation.current = current;
    setSubmitting(true);
    setSubmitError('');
    setSubmitNotice('');
    try {
      await repository.submit(token, selectedSessionId, selectedEmotion, current.controller.signal);
      if (mutation.current !== current) return;
      setSelectedEmotion(null);
      setSubmitNotice(repository.mode === 'demo' ? '演示反馈已记录。' : '反馈已保存。');
      retry();
    } catch (error) {
      if (mutation.current === current && !expire(error))
        setSubmitError(
          writeResultIsUnknown(error)
            ? `${messageOf(error)} 请先查看历史核实结果，再决定是否重试。`
            : messageOf(error),
        );
    } finally {
      if (mutation.current === current) {
        mutation.current = null;
        setSubmitting(false);
      }
    }
  };
  return {
    sessions,
    selectedSessionId,
    sessionsLoading,
    sessionsError,
    records,
    historyLoading,
    historyError,
    statistics,
    statisticsLoading,
    statisticsError,
    selectedEmotion,
    submitting,
    submitError,
    submitNotice,
    canSubmit,
    selectSession: (id: string) => {
      if (!mutation.current) setSelectedSessionId(id);
    },
    selectEmotion: (emotion: Emotion) => {
      setSelectedEmotion(emotion);
      setSubmitError('');
      setSubmitNotice('');
    },
    retrySessions: () => setSessionsVersion((value) => value + 1),
    retry,
    submit,
  };
}
