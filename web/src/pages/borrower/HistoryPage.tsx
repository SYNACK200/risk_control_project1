import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listMyTasks, withdrawConsent, type BorrowerTaskItem } from '../../api/borrower';
import { getErrorMessage } from '../../api/errors';
import { Notice } from '../../ui/Notice';

function statusBadge(status: string): { label: string; cls: string } {
  switch (status) {
    case 'DONE':
      return { label: '处理完成', cls: 'pill ok' };
    case 'FAILED':
      return { label: '未完成', cls: 'pill err' };
    case 'NEED_SUPPLEMENT':
      return { label: '需补充材料', cls: 'pill warn' };
    case 'QUEUED':
    case 'PENDING':
      return { label: '排队受理中', cls: 'pill' };
    default:
      return { label: '处理中', cls: 'pill warn' };
  }
}

export default function HistoryPage() {
  const [items, setItems] = useState<BorrowerTaskItem[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [confirmWithdrawId, setConfirmWithdrawId] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    listMyTasks(50)
      .then((res) => {
        setItems(res.items || []);
        setError('');
      })
      .catch((err) => setError(getErrorMessage(err, 'borrower')))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleWithdraw(taskId: number) {
    setBusyId(taskId);
    setError('');
    setNotice('');
    try {
      await withdrawConsent(taskId);
      setConfirmWithdrawId(null);
      setNotice(`已撤回任务 #${taskId} 的信息处理授权，相关原始材料已进入清理流程。`);
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'borrower'));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="panel">
      <header className="panel-head">
        <div>
          <h1>我的提交记录</h1>
          <p className="sub">按提交时间查看每笔材料的受理进度与授权状态；审核结论由银行侧查阅。</p>
        </div>
        <Link className="btn" to="/app/upload">
          + 上传新流水
        </Link>
      </header>

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="ok">{notice}</Notice> : null}
      {loading ? <p className="muted">加载中…</p> : null}

      {!loading && items.length === 0 ? (
        <p className="muted">还没有提交记录，点击右上角「上传新流水」开始。</p>
      ) : null}

      {items.length > 0 ? (
        <table className="grid">
          <thead>
            <tr>
              <th>业务编号</th>
              <th>材料格式</th>
              <th>覆盖区间</th>
              <th>授权版本</th>
              <th>当前状态</th>
              <th>提交时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const badge = statusBadge(item.status);
              return (
                <tr key={item.id}>
                  <td className="mono small">{item.biz_no}</td>
                  <td className="small muted">{item.carrier || 'PDF'}</td>
                  <td className="small muted">
                    {item.period_start || item.period_end
                      ? `${item.period_start || '—'} 至 ${item.period_end || '—'}`
                      : '自动识别'}
                  </td>
                  <td className="small muted">{item.consent_version || '已授权'}</td>
                  <td>
                    <span className={badge.cls}>{badge.label}</span>
                  </td>
                  <td className="small muted">
                    {item.created_at ? new Date(item.created_at).toLocaleString() : '—'}
                  </td>
                  <td className="actions-cell">
                    <Link className="link-btn" to={'/app/tasks/' + item.id}>
                      {item.status === 'NEED_SUPPLEMENT' ? '补充材料' : '查看进度'}
                    </Link>
                    {confirmWithdrawId === item.id ? (
                      <>
                        <button
                          type="button"
                          className="link-btn danger"
                          disabled={busyId === item.id}
                          onClick={() => void handleWithdraw(item.id)}
                        >
                          {busyId === item.id ? '撤回中…' : '确认撤回并删除'}
                        </button>
                        <button type="button" className="link-btn" onClick={() => setConfirmWithdrawId(null)}>
                          取消
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="link-btn danger"
                        onClick={() => setConfirmWithdrawId(item.id)}
                      >
                        撤回授权
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}
