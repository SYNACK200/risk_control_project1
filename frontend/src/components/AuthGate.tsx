import { useEffect, useState, type ReactNode } from 'react';
import { AUTH_REQUIRED_EVENT, clearToken, getToken } from '../lib/auth';
import { UserBar } from './UserBar';

export function AuthGate({ children }: { children: ReactNode }) {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [blocked, setBlocked] = useState(false);

  useEffect(() => {
    async function check() {
      const token = getToken();
      if (!token) { setAuthed(false); return; }
      try {
        const res = await fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + token } });
        if (!res.ok) { clearToken(); setAuthed(false); return; }
        const data = await res.json();
        if (data.user?.role !== 'borrower') {
          clearToken();
          localStorage.removeItem('bs_user');
          setBlocked(true);
          setAuthed(false);
          return;
        }
        localStorage.setItem('bs_user', JSON.stringify(data.user));
        setAuthed(true);
      } catch {
        setAuthed(false);
      }
    }
    void check();
    const onRequired = () => { clearToken(); setAuthed(false); };
    window.addEventListener(AUTH_REQUIRED_EVENT, onRequired);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onRequired);
  }, []);

  if (authed === null) return <div className="auth-gate muted">正在检查登录状态…</div>;
  if (blocked) {
    return (
      <div className="auth-gate role-block">
        <div className="role-block-card">
          <strong>这个账号属于银行侧</strong>
          <p className="muted">借款侧只接受借款账号。请回到首页，从「银行侧」入口登录。</p>
          <div className="role-block-actions">
            <a className="pill-btn pill-btn-primary" href="/bank/">去银行侧登录</a>
            <a className="pill-btn" href="/">回首页</a>
          </div>
        </div>
      </div>
    );
  }
  if (!authed) {
    // 统一入口：借款侧未登录时也走 /login（身份预选借款侧），不再维护第二套登录页
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
      window.location.replace('/login?role=borrower');
    }
    return <div className="auth-gate muted">正在跳转登录…</div>;
  }
  return <><UserBar />{children}</>;
}
