import { useEffect, useState } from 'react';
import { listAuditLogs, type AuditLogRow } from '../lib/api';

/** 审计日志（只读）：谁在什么时候改了什么，用于追责与复盘。 */
export function AuditPage() {
  const [rows, setRows] = useState<AuditLogRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [action, setAction] = useState('');
  const [error, setError] = useState('');
  const size = 30;

  useEffect(() => {
    listAuditLogs({ page, size, action: action || undefined })
      .then(d => { setRows(d.items); setTotal(d.total); })
      .catch(e => setError(e instanceof Error ? e.message : String(e)));
  }, [page, action]);

  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="result">
      <div className="result-head">
        <h2>审计日志</h2>
        <span className="muted">共 {total} 条 · 只读，不提供删除</span>
      </div>
      {error && <div className="notice error">{error}</div>}
      <section className="card">
        <div className="card-body">
          <div className="tpl-row">
            <label className="muted small">动作</label>
            <input className="thr-input" placeholder="如 threshold.save（留空看全部）" value={action}
              onChange={e => { setAction(e.target.value); setPage(1); }} />
            <button className="pill-btn" type="button" disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>上一页</button>
            <span className="muted small">{page} / {pages}</span>
            <button className="pill-btn" type="button" disabled={page >= pages} onClick={() => setPage(p => p + 1)}>下一页</button>
          </div>
          <table className="mini">
            <thead><tr><th>时间</th><th>动作</th><th>对象</th><th>操作人</th><th>详情</th></tr></thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.id}>
                  <td className="mono small">{(r.created_at ?? '').replace('T', ' ').slice(0, 19)}</td>
                  <td className="mono">{r.action}</td>
                  <td className="muted small">{r.object_type ?? '—'}{r.object_id ? ' #' + r.object_id : ''}</td>
                  <td className="muted small">{r.actor_id ?? '—'}</td>
                  <td className="muted small">{(r.detail ?? '').slice(0, 80)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && !error && <p className="muted">没有记录。</p>}
        </div>
      </section>
    </div>
  );
}
