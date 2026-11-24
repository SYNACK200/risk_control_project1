import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { request } from '../../api/client';
import { ApiError, getErrorMessage } from '../../api/errors';
import { homeFor, setSession, type MeUser } from '../../auth/store';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';

type LoginResponse = { token?: string; access_token?: string; user: MeUser };

export default function LoginPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [role, setRole] = useState<'banker' | 'borrower'>(params.get('role') === 'borrower' ? 'borrower' : 'banker');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await request<LoginResponse>('/auth/login', { body: { username, password } });
      const token = data.token ?? data.access_token;
      if (!token || !data.user) throw new ApiError('E_UNKNOWN', '登录响应缺少凭据');
      setSession(token, data.user);
      navigate(homeFor(data.user), { replace: true });
    } catch (err) {
      // 借款侧与银行侧对同一个错误码说法不同，这里按选择的身份取值
      setError(getErrorMessage(err, role === 'banker' ? 'banker' : 'borrower'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-center">
      <div className="auth-shell">
        <aside className="auth-aside">
          <div>
            <h2>流水真实性核验</h2>
            <p>四层核验、五态结论、40 项指标与可追溯报告。</p>
            <ul>
              <li>载体 / 内容 / 账务 / 外部 四层核验</li>
              <li>C1–C10 检查，关键项一票否决</li>
              <li>统一口径的特征库与版本化指标</li>
            </ul>
          </div>
          <p className="tip">银行内部自建工具 · 报告仅银行侧可见</p>
        </aside>

        <form className="auth-form" onSubmit={submit}>
          <header className="brand">
            <i>风</i>
            <span>智能风控</span>
          </header>
          <h1>登录</h1>
          <p className="sub">请选择身份后登录</p>

          <div className="tabs" role="tablist">
            <button type="button" className={role === 'banker' ? 'active' : ''} onClick={() => setRole('banker')}>
              银行员工
            </button>
            <button type="button" className={role === 'borrower' ? 'active' : ''} onClick={() => setRole('borrower')}>
              借款人
            </button>
          </div>

          <Field label="用户名" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
          <Field
            label="密码"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />

          {error ? <Notice>{error}</Notice> : null}

          <Button type="submit" block disabled={busy}>
            {busy ? '登录中…' : '登录'}
          </Button>

          <p className="auth-foot">
            借款人还没有账号？<Link to="/register">注册</Link>
            <span className="sep">·</span>
            <Link to="/">返回首页</Link>
          </p>
          <p className="small muted" style={{ textAlign: 'center', marginTop: 6 }}>
            忘记密码？请联系银行系统管理员协助重置。
          </p>
        </form>
      </div>
    </div>
  );
}
