import { useEffect, useState } from 'react';
const TOKEN_KEY = 'bs_token';

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export const AUTH_REQUIRED_EVENT = 'dsh-auth-required';

export function notifyAuthRequired() {
  window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT));
}

export type MeUser = {
  id: number; username: string; role: string;
  display_name?: string | null; is_admin?: boolean;
};

/** 当前登录用户：先读本地缓存，再向后端 /auth/me 校准（is_admin 以服务端为准）。 */
export function getStoredUser(): MeUser | null {
  try {
    const raw = localStorage.getItem('bs_user');
    return raw ? (JSON.parse(raw) as MeUser) : null;
  } catch {
    return null;
  }
}

export function useMe(): MeUser | null {
  const [me, setMe] = useState<MeUser | null>(() => getStoredUser());
  useEffect(() => {
    let alive = true;
    const token = localStorage.getItem('bs_token');
    if (!token) { setMe(null); return () => { alive = false; }; }
    fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + token } })
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (!alive || !d?.user) return;
        const user = d.user as MeUser;
        localStorage.setItem('bs_user', JSON.stringify(user));
        setMe(user);
      })
      .catch(() => undefined);
    return () => { alive = false; };
  }, []);
  return me;
}

/** 银行侧管理员才可改阈值、启停/删模板、删任务、看审计、管账号。 */
export function useIsAdmin(): boolean {
  const me = useMe();
  return Boolean(me && me.role === 'banker' && me.is_admin);
}
