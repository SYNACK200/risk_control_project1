import { useEffect, useRef, useState, type ReactNode } from 'react';
import { AUTH_REQUIRED_EVENT, clearToken, getToken, setToken } from '../lib/auth';

const PROBE = '/api/v1/tasks?limit=1';

export function AuthGate({ children }: { children: ReactNode }) {
  const [needAuth, setNeedAuth] = useState(false);
  const [checking, setChecking] = useState(true);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const token = getToken();
    fetch(PROBE, { headers: token ? { Authorization: 'Bearer ' + token } : {} })
      .then(res => setNeedAuth(res.status === 401 || res.status === 503))
      .catch(() => setNeedAuth(false))
      .finally(() => setChecking(false));
    const onRequired = () => setNeedAuth(true);
    window.addEventListener(AUTH_REQUIRED_EVENT, onRequired);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onRequired);
  }, []);

  if (checking) return <div className="auth-gate muted">正在检查本地访问权限…</div>;
  if (!needAuth) return <>{children}</>;

  return (
    <div className="auth-gate">
      <form
        className="auth-gate-card"
        onSubmit={async e => {
          e.preventDefault();
          setError('');
          const token = (inputRef.current?.value ?? '').trim();
          if (!token) {
            setError('请输入口令');
            return;
          }
          setToken(token);
          try {
            const res = await fetch(PROBE, { headers: { Authorization: 'Bearer ' + token } });
            if (res.status === 401) {
              clearToken();
              setError('口令不正确');
              return;
            }
            if (res.status === 503) {
              setError('服务端未配置 LOCAL_ACCESS_PASSWORD');
              return;
            }
            setNeedAuth(false);
          } catch (err) {
            setError(err instanceof Error ? err.message : '校验失败');
          }
        }}
      >
        <h2>需要本地访问口令</h2>
        <p className="muted">后端已开启本地保护，口令来自启动后端时的 LOCAL_ACCESS_PASSWORD。</p>
        <input type="password" ref={inputRef} placeholder="本地访问口令" autoFocus />
        {error && <p className="me-warn">{error}</p>}
        <button className="btn" type="submit">进入</button>
      </form>
    </div>
  );
}
