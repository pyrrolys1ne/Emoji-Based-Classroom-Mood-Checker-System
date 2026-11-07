import { useState } from 'react';
import type { TeacherApplication, User } from '@mood/contracts';
import { useManagementAction, useManagementList } from '../controllers/useManagement';
import {
  canManage,
  managementNotice,
  managementRepository as repo,
} from '../repositories/managementRepository';
import { ManagementForm } from './components/ManagementForm';

const statusNames = { PENDING: '待审批', APPROVED: '已批准', REJECTED: '已驳回' };
export function TeachersPage({ users, changed }: { users: User[]; changed: () => Promise<void> }) {
  const list = useManagementList(repo.applications);
  const [filter, setFilter] = useState('PENDING');
  const [review, setReview] = useState<{
    application: TeacherApplication;
    decision: 'APPROVED' | 'REJECTED';
  } | null>(null);
  const [message, setMessage] = useState('');
  const visible = list.items.filter((item) => !filter || item.status === filter);
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>教师申请审批</h2>
          <p>审核通过后账号获得教师权限，历史审批结果保留</p>
        </div>
        <button
          className="button secondary"
          disabled={!canManage || list.loading}
          onClick={() => void list.refresh()}
        >
          刷新申请
        </button>
      </div>
      {!canManage ? (
        <p className="management-note">{managementNotice}</p>
      ) : (
        <>
          <div className="filters">
            <label>
              申请状态{' '}
              <select value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="PENDING">待审批</option>
                <option value="APPROVED">已批准</option>
                <option value="REJECTED">已驳回</option>
                <option value="">全部申请</option>
              </select>
            </label>
            <span>待审批 {list.items.filter((x) => x.status === 'PENDING').length} 条</span>
          </div>
          {message && (
            <p className="management-note success-message" role="status">
              {message}
            </p>
          )}
          {list.error && (
            <p className="management-note error" role="alert">
              {list.error}（保留上次结果，请刷新核对）
            </p>
          )}
          {list.loading ? (
            <p className="empty">正在加载申请…</p>
          ) : !visible.length ? (
            <p className="empty">暂无符合条件的申请</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>申请人</th>
                    <th>提交时间</th>
                    <th>状态</th>
                    <th>审核信息</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((item) => {
                    const user = users.find((u) => u.id === item.userId);
                    const actionable =
                      item.status === 'PENDING' &&
                      user?.status === 'ACTIVE' &&
                      user.role === 'STUDENT';
                    return (
                      <tr key={item.id}>
                        <td>
                          {user?.realName || user?.username || item.userId}
                          <small>{user?.email}</small>
                        </td>
                        <td>{new Date(item.submittedAt).toLocaleString('zh-CN')}</td>
                        <td>
                          <span className="tag">{statusNames[item.status]}</span>
                        </td>
                        <td>
                          {item.reason || '—'}
                          <small>
                            {item.reviewedAt
                              ? new Date(item.reviewedAt).toLocaleString('zh-CN')
                              : '尚未审核'}
                          </small>
                        </td>
                        <td>
                          <div className="management-actions">
                            <button
                              className="text-button"
                              disabled={!actionable}
                              onClick={() => setReview({ application: item, decision: 'APPROVED' })}
                            >
                              批准
                            </button>
                            <button
                              className="text-button danger-text"
                              disabled={!actionable}
                              onClick={() => setReview({ application: item, decision: 'REJECTED' })}
                            >
                              驳回
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {review && (
        <ReviewForm
          key={review.application.id + review.decision}
          {...review}
          applicant={users.find((u) => u.id === review.application.userId)}
          close={() => setReview(null)}
          saved={async () => {
            setReview(null);
            setMessage('审批已保存。');
            await Promise.all([list.refresh(), changed()]);
          }}
        />
      )}
    </section>
  );
}

function ReviewForm({
  application,
  decision,
  applicant,
  close,
  saved,
}: {
  application: TeacherApplication;
  decision: 'APPROVED' | 'REJECTED';
  applicant?: User;
  close: () => void;
  saved: () => Promise<void>;
}) {
  const [reason, setReason] = useState('');
  const action = useManagementAction();
  return (
    <ManagementForm
      title={decision === 'APPROVED' ? '批准教师申请' : '驳回教师申请'}
      busy={action.busy}
      error={action.error}
      close={close}
      submit={() =>
        void action.run(async () => {
          await repo.review(application.id, { decision, reason: reason.trim() || null });
          await saved();
        })
      }
    >
      <p>
        {applicant?.realName || applicant?.username || application.userId} · {applicant?.email}
      </p>
      <p className="muted">
        {decision === 'APPROVED'
          ? '批准后账号可登录教师端，只能查看所授课堂。'
          : '驳回后该教师申请不能用于登录。'}
      </p>
      <label>
        审核说明（选填）
        <textarea
          rows={3}
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
    </ManagementForm>
  );
}
