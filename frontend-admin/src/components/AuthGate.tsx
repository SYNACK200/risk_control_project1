import { useEffect, useState, type ReactNode } from 'react';
import { AUTH_REQUIRED_EVENT, clearToken, getToken } from '../lib/auth';
import { LoginPage } from '../pages/LoginPage';

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<'checking' | 'login' | 'ok' | 'forbidden'>('checking');

  useEffect(() => {
    async function check() {
      const token = getToken();
      if (!token) { setState('login'); return; }
      try {
        const res = await fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + token } });
        if (!res.ok) { clearToken(); setState('login'); return; }
        const data = await res.json();
        if (data.user.role !== 'banker') { setState('forbidden'); return; }
        localStorage.setItem('bs_user', JSON.stringify(data.user));
        setState('ok');
      } catch { setState('login'); }
    }
    void check();
    const onRequired = () => { clearToken(); setState('login'); };
    window.addEventListener(AUTH_REQUIRED_EVENT, onRequired);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onRequired);
  }, []);

  if (state === 'checking') return <div className="auth-gate muted">正在检查登录状态…</div>;
  if (state === 'login') return <LoginPage />;
  if (state === 'forbidden') {
    return (
      <div className="auth-gate">
        <div className="auth-gate-card">
          {/* 不提示账号属于哪一侧：避免把「这个用户名是哪类账号」暴露给旁人。 */}
          <h2>当前账号无法使用本页面</h2>
          <p className="muted">请换一个账号，或联系管理员确认权限。</p>
          <button className="btn" type="button" onClick={() => { clearToken(); window.location.reload(); }}>换账号</button>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}