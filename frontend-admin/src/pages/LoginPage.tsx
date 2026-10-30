import { useState } from 'react';
import { setToken } from '../lib/auth';

const BASE = '/api/v1';

export function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const res = await fetch(BASE + '/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        setError(data?.detail?.message || '登录失败（' + res.status + '）');
        return;
      }
      if (data.user.role !== 'banker') {
        setError('这是借款侧账号，请用银行侧账号登录，或去借款端 5173。');
        return;
      }
      setToken(data.token);
      localStorage.setItem('bs_user', JSON.stringify(data.user));
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : '网络错误');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-gate">
      <form className="auth-gate-card" onSubmit={submit}>
        <h2>银行侧登录</h2>
        <p className="muted">只有银行侧账号可以进入；借款侧请使用 5173 的借款人入口。</p>
        <input placeholder="用户名" value={username} onChange={e => setUsername(e.target.value)} autoFocus />
        <input type="password" placeholder="密码" value={password} onChange={e => setPassword(e.target.value)} />
        {error && <p className="me-warn">{error}</p>}
        <button className="btn" type="submit" disabled={busy}>{busy ? '登录中…' : '登录'}</button>
        <p className="muted small">首次启动的默认账号：admin / admin123（登录后请修改密码）</p>
      </form>
    </div>
  );
}
