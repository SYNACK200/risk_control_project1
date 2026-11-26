import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  cancelQueueJob,
  getQueueStats,
  listQueueJobs,
  retryQueueJob,
  type QueueJobItem,
  type QueueStats,
} from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { PageHeader } from '../../ui/PageHeader';

const STAGE_LABELS: Record<string, string> = {
  QUEUED: '排队等待',
  CHECKING: '预检中',
  PARSING: '解析中',
  VERIFYING: '核验中',
  REPORTING: '生成报告',
  FAILED: '已失败 / 已取消',
};

export default function QueuePage({ embedded = false, active = true }: { embedded?: boolean; active?: boolean } = {}) {
  const [stats, setStats] = useState<QueueStats | null>(null);
  const [jobs, setJobs] = useState<QueueJobItem[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(() => {
    Promise.all([getQueueStats(), listQueueJobs(true)])
      .then(([st, list]) => {
        setStats(st);
        setJobs(list.items ?? []);
        setError('');
      })
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  }, []);

  // 嵌在任务中心时只有停在「队列」页签才轮询，切走即停
  useEffect(() => {
    if (!active) return;
    load();
    if (!autoRefresh) return;
    const id = window.setInterval(load, 5000);
    return () => window.clearInterval(id);
  }, [load, autoRefresh, active]);

  async function handleRetry(taskId: number) {
    setBusyId(taskId);
    setError('');
    setNotice('');
    try {
      await retryQueueJob(taskId);
      setNotice(`任务 #${taskId} 已重新加入解析队列。`);
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusyId(null);
    }
  }

  async function handleCancel(taskId: number) {
    setBusyId(taskId);
    setError('');
    setNotice('');
    try {
      await cancelQueueJob(taskId);
      setNotice(`任务 #${taskId} 已取消排队。`);
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className={embedded ? undefined : 'panel wide'}>
      <PageHeader
        title={embedded ? undefined : '任务队列'}
        description="队列是任务的实时视图：排队位次、当前执行阶段与失败任务，可一键重试或取消排队。"
        actions={
          <div className="filters">
            <label className="inline-check">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              每 5 秒自动刷新
            </label>
            <Button size="sm" variant="ghost" onClick={load}>立即刷新</Button>
          </div>
        }
      />

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="ok">{notice}</Notice> : null}

      {stats ? (
        <section className="score-row">
          <div className="score">
            <span className="score-value">{stats.queued}</span>
            <span className="muted small">排队中</span>
          </div>
          <div className="score">
            <span className="score-value">{stats.running}</span>
            <span className="muted small">处理中（进程 {stats.active_workers}/{stats.max_workers}）</span>
          </div>
          <div className="score">
            <span className="score-value">{stats.failed}</span>
            <span className="muted small">失败 / 待重试</span>
          </div>
          <div className="score">
            <span className="score-value">{stats.done}</span>
            <span className="muted small">累计已完成</span>
          </div>
        </section>
      ) : null}

      <section style={{ marginTop: 16 }}>
        <h2>活跃与失败任务（{jobs.length}）</h2>
        {jobs.length === 0 ? (
          <p className="muted small">当前队列空闲，没有排队或失败任务。</p>
        ) : (
          <table className="grid compact">
            <thead>
              <tr>
                <th>任务</th>
                <th>排队位次</th>
                <th>当前阶段</th>
                <th>载体</th>
                <th>失败原因码</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.task_id}>
                  <td>
                    <strong>{job.biz_no}</strong>
                    <div className="small muted">#{job.task_id}</div>
                  </td>
                  <td className="mono">{job.queue_position ? `第 ${job.queue_position} 位` : '—'}</td>
                  <td>
                    <span className={'pill ' + (job.status === 'FAILED' ? 'err' : 'warn')}>
                      {STAGE_LABELS[job.status] ?? job.status}
                    </span>
                  </td>
                  <td className="small muted">{job.carrier || '—'}</td>
                  <td className="mono small">{job.failure_code || '—'}</td>
                  <td className="small muted">{job.created_at ? new Date(job.created_at).toLocaleString() : '—'}</td>
                  <td className="actions-cell">
                    {job.status === 'FAILED' ? (
                      <button
                        type="button"
                        className="link-btn"
                        disabled={busyId === job.task_id}
                        onClick={() => void handleRetry(job.task_id)}
                      >
                        {busyId === job.task_id ? '提交中…' : '重试'}
                      </button>
                    ) : null}
                    {job.status === 'QUEUED' ? (
                      <button
                        type="button"
                        className="link-btn danger"
                        disabled={busyId === job.task_id}
                        onClick={() => void handleCancel(job.task_id)}
                      >
                        取消
                      </button>
                    ) : null}
                    <Link className="link-btn" to={'/bank/annotate?taskId=' + job.task_id}>调框</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
