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
