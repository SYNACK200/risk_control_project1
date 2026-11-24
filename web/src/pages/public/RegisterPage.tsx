import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { request } from '../../api/client';
import { getErrorMessage } from '../../api/errors';
import { setSession, type MeUser } from '../../auth/store';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';

type RegisterResponse = { token?: string; access_token?: string; user?: MeUser };

export default function RegisterPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError('两次输入的密码不一致');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const data = await request<RegisterResponse>('/auth/register', {
        body: { username, password, display_name: displayName || undefined },
      });
      const token = data.token ?? data.access_token;
      if (token && data.user) {
        setSession(token, data.user);
        navigate('/app', { replace: true });
        return;
      }
      navigate('/login?role=borrower', { replace: true });
    } catch (err) {
      setError(getErrorMessage(err, 'borrower'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-center">
      <form className="auth-shell single" onSubmit={submit}>
        <header className="brand">
          <i>风</i>
          <span>智能风控</span>
        </header>
        <h1>注册借款人账号</h1>
        <p className="sub">银行员工账号由管理员创建，不能自助注册。</p>

        <Field label="用户名" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        <Field label="显示名（可选）" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        <Field
          label="密码"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
          required
        />
        <Field
          label="确认密码"
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          autoComplete="new-password"
          required
        />

        {error ? <Notice>{error}</Notice> : null}

        <Button type="submit" block disabled={busy}>
          {busy ? '注册中…' : '注册'}
        </Button>

        <p className="auth-foot">
          已有账号？<Link to="/login?role=borrower">去登录</Link>
          <span className="sep">·</span>
          <Link to="/">返回首页</Link>
        </p>
      </form>
    </div>
  );
}
