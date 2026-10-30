import { useState } from 'react';
import { setToken } from '../lib/auth';

const BASE = '/api/v1';

export function LoginPage() {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (sessionStorage) sessionStorage.clear();
    if (username.trim().length < 3) { setError('用户名至少 3 个字符'); return; }
    if (password.length < 6) { setError('密码至少 6 位'); return; }
    setBusy(true);
    try {
      const path = mode === 'login' ? '/auth/login' : '/auth/register';
      const body = mode === 'login'
        ? { username: username.trim(), password }
        : { username: username.trim(), password, display_name: displayName.trim() || undefined };
      const res = await fetch(BASE + path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        setError(data?.detail?.message || '操作失败（' + res.status + '）');
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
        <h2>{mode === 'login' ? '借款人登录' : '注册账号'}</h2>
        <p className="muted">用于提交与查看自己的流水；银行侧请用银行账号登录银行端。</p>
        <input placeholder="用户名" value={username} onChange={e => setUsername(e.target.value)} autoFocus />
        <input type="password" placeholder="密码（至少 6 位）" value={password} onChange={e => setPassword(e.target.value)} />
        {mode === 'register' && (
          <input placeholder="显示名称（可选，如：张三）" value={displayName} onChange={e => setDisplayName(e.target.value)} />
        )}
        {error && <p className="me-warn">{error}</p>}
        <button className="btn" type="submit" disabled={busy}>{busy ? '处理中…' : mode === 'login' ? '登录' : '注册并登录'}</button>
        <button className="link-btn" type="button" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}>
          {mode === 'login' ? '没有账号？去注册' : '已有账号？去登录'}
        </button>
      </form>
    </div>
  );
}
