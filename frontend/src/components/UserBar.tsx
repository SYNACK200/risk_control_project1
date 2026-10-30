import { useEffect, useState } from 'react';

export function UserBar() {
  const [name, setName] = useState('');
  const [role, setRole] = useState('');

  useEffect(() => {
    try {
      const raw = localStorage.getItem('bs_user');
      if (!raw) return;
      const user = JSON.parse(raw);
      setName(user.display_name || user.username || '');
      setRole(user.role === 'banker' ? '银行侧' : '借款侧');
    } catch { /* ignore */ }
  }, []);

  if (!name) return null;
  return (
    <div className="user-bar">
      <span className="muted">{role} · {name}</span>
      <button
        className="link-btn"
        type="button"
        onClick={() => {
          localStorage.removeItem('bs_user');
          localStorage.removeItem('bs_token');
          window.location.reload();
        }}
      >退出登录</button>
    </div>
  );
}
