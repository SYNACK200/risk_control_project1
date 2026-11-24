import { useEffect, useState } from 'react';
import { listAudit, type AuditRow } from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { Notice } from '../../ui/Notice';

export default function AuditPage() {
  const PAGE = 20;
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [actionFilter, setActionFilter] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    listAudit({ page, size: PAGE, action: actionFilter.trim() || undefined })
      .then((data) => {
        setRows(data.items);
        setTotal(data.total);
        setError('');
      })
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  }, [page, actionFilter]);

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>操作审计</h1>
          <p className="sub">只读，不可修改或删除；共 {total} 条，当前第 {page} 页。</p>
        </div>
        <div className="filters">
          <input
            className="search"
            placeholder="按动作类型服务端筛选（如 task. / template.）"
            value={actionFilter}
            onChange={(e) => {
              setActionFilter(e.target.value);
              setPage(1);
            }}
          />
          <button type="button" className="btn btn-ghost" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>上一页</button>
          <button type="button" className="btn btn-ghost" disabled={page * PAGE >= total} onClick={() => setPage((p) => p + 1)}>下一页</button>
        </div>
      </header>
      {error ? <Notice>{error}</Notice> : null}
      <div className="scroll">
        <table className="grid compact">
          <thead>
            <tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th><th>详情</th></tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="small">{row.created_at ? new Date(row.created_at).toLocaleString() : '—'}</td>
                <td>{row.actor_id ?? '系统'}</td>
                <td>{row.action}</td>
                <td className="small muted">{row.object_type ? row.object_type + '#' + (row.object_id ?? '') : '—'}</td>
                <td className="small muted">{row.detail ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
