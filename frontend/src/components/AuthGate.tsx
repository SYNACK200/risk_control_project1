import { useEffect, useState, type ReactNode } from 'react';
import { AUTH_REQUIRED_EVENT, clearToken, getToken } from '../lib/auth';
import { LoginPage } from '../pages/LoginPage';
import { UserBar } from './UserBar';

export function AuthGate({ children }: { children: ReactNode }) {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    async function check() {
      const token = getToken();
      if (!token) { setAuthed(false); return; }
      try {
        const res = await fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + token } });
        if (!res.ok) { clearToken(); setAuthed(false); return; }
        const data = await res.json();
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
  if (!authed) return <LoginPage />;
  return <><UserBar />{children}</>;
}
