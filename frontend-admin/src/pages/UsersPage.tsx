import { useEffect, useState } from 'react';
import { listUsers, type AppUserRow } from '../lib/api';

/** 账号（只读列表）：谁在用这套系统，角色是什么。新建账号走接口，这里先不提供表单。 */
export function UsersPage() {
  const [rows, setRows] = useState<AppUserRow[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    listUsers()
      .then(d => setRows(d.items))
      .catch(e => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="result">
      <div className="result-head">
        <h2>账号</h2>
        <span className="muted">{rows.length} 个账号 · 角色分为银行侧与借款侧</span>
      </div>
      {error && <div className="notice error">{error}</div>}
      <section className="card">
        <div className="card-body">
          <table className="mini">
            <thead><tr><th>ID</th><th>用户名</th><th>角色</th><th>显示名</th><th>状态</th></tr></thead>
            <tbody>
              {rows.map(u => (
                <tr key={u.id}>
                  <td className="mono">{u.id}</td>
                  <td className="mono">{u.username}</td>
                  <td><span className={'tag ' + (u.role === 'banker' ? 'pass' : 'limited')}>{u.role === 'banker' ? '银行侧' : '借款侧'}</span></td>
                  <td className="muted small">{u.display_name ?? '—'}</td>
                  <td className="muted small">{u.status ?? 'active'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && !error && <p className="muted">加载中…</p>}
        </div>
      </section>
    </div>
  );
}
