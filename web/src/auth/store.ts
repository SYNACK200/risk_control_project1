/**
 * 会话状态：唯一一份 localStorage 逻辑。
 *
 * 键名沿用旧版的 bs_token / bs_user：合并期间新旧页面会并存，
 * 换了键名就会出现「在这里登录、在那边还是未登录」。
 */
export type MeUser = {
  id: number;
  username: string;
  role: 'borrower' | 'banker' | string;
  display_name?: string | null;
  is_admin?: boolean;
};

const TOKEN_KEY = 'bs_token';
const USER_KEY = 'bs_user';

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getUser(): MeUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as MeUser) : null;
  } catch {
    return null;
  }
}

export function setSession(token: string, user: MeUser) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function homeFor(user: MeUser | null): string {
  if (!user) return '/login';
  return user.role === 'banker' ? '/bank' : '/app';
}
