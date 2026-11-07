import { useEffect, useState } from 'react';
import { createBankUser, disableUser, listUsers, type AppUserRow } from '../lib/api';
import { useIsAdmin, useMe } from '../lib/auth';

/**
 * 账号：谁在用这套系统、角色是什么。
 *
 * 权限分离（界面与后端一致）：
 *   - 借款侧账号由借款人自助注册（/login 的注册入口），银行侧不代为创建；
 *   - 银行侧账号只能由管理员在这里添加，且只能创建 banker，不能建 borrower；
 *   - 非管理员看得到列表、看不到表单。
 */
export function UsersPage() {
  const isAdmin = useIsAdmin();
  const me = useMe();
  const [rows, setRows] = useState<AppUserRow[]>([]);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ username: '', password: '', display_name: '' });

  function load() {
    listUsers()
      .then(d => setRows(d.items))
      .catch(e => setError(e instanceof Error ? e.message : String(e)));
  }
  useEffect(load, []);

  async function removeUser(u: AppUserRow) {
    if (!window.confirm('停用后 ' + u.username + ' 将无法登录（历史审计记录保留）。继续？')) return;
    setBusy(true); setError(''); setMsg('');
    try {
      await disableUser(u.id);
      setMsg('已停用 ' + u.username);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    setError(''); setMsg('');
    const username = form.username.trim();
    if (username.length < 3) { setError('用户名至少 3 个字符'); return; }
    if (form.password.length < 6) { setError('密码至少 6 位'); return; }
    setBusy(true);
    try {
      await createBankUser({ username, password: form.password,
        display_name: form.display_name.trim() || undefined });
      setMsg('已创建银行侧账号 ' + username + '（默认无管理权限）');
      setForm({ username: '', password: '', display_name: '' });
      setFormOpen(false);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="result">
      <div className="result-head">
        <h2>账号</h2>
        <span className="muted">{rows.length} 个账号 · 银行侧与借款侧分离</span>
      </div>
      {error && <div className="notice error">{error}</div>}
      {msg && <div className="notice info">{msg}</div>}

      <section className="card">
        <div className="card-head-static">
          <strong>银行侧账号</strong>
          <span className="muted small">
            {isAdmin ? '管理员可添加；新账号默认无管理权限（不能改阈值/启停模板/删任务）' : '仅管理员可添加'}
          </span>
        </div>
        <div className="card-body">
          {isAdmin && (
            <div className="tpl-row" style={{ marginBottom: 10 }}>
              <button className="btn" type="button" onClick={() => setFormOpen(v => !v)}>
                {formOpen ? '收起表单' : '+ 添加银行侧账号'}
              </button>
            </div>
          )}
          {formOpen && isAdmin && (
            <div className="tpl-row" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
              <input placeholder="用户名（登录用，≥3 位）" value={form.username}
                onChange={e => setForm(p => ({ ...p, username: e.target.value }))} style={{ width: 190 }} />
              <input placeholder="初始密码（≥6 位）" type="password" value={form.password}
                onChange={e => setForm(p => ({ ...p, password: e.target.value }))} style={{ width: 190 }} />
              <input placeholder="显示名（可选）" value={form.display_name}
                onChange={e => setForm(p => ({ ...p, display_name: e.target.value }))} style={{ width: 170 }} />
              <button className="btn" type="button" disabled={busy} onClick={() => { void submit(); }}>
                {busy ? '创建中…' : '创建'}
              </button>
            </div>
          )}
          <table className="mini">
            <thead><tr><th>ID</th><th>用户名</th><th>角色</th><th>权限</th><th>显示名</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              {rows.map(u => (
                <tr key={u.id}>
                  <td className="mono">{u.id}</td>
                  <td className="mono">{u.username}</td>
                  <td><span className={'tag ' + (u.role === 'banker' ? 'pass' : 'limited')}>{u.role === 'banker' ? '银行侧' : '借款侧'}</span></td>
                  <td className="muted small">{u.role === 'banker' ? (u.is_admin ? '管理员' : '员工') : '—'}</td>
                  <td className="muted small">{u.display_name ?? '—'}</td>
                  <td className="muted small">{u.status ?? 'active'}</td>
                  <td>
                    {isAdmin && u.id !== me?.id && (u.status ?? 'active') === 'active' && (
                      <button className="link-btn danger-text" type="button" disabled={busy}
                        onClick={() => { void removeUser(u); }}>停用</button>
                    )}
                  </td>
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