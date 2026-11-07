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
      // 不把侧别写到界面上：屏幕共享、截图都会留下来
      setRole('');
    } catch { /* ignore */ }
  }, []);

  if (!name) return null;
  return (
    <div className="user-bar">
      <span className="muted">{role ? role + ' · ' : ''}{name}</span>
      <button
        className="link-btn"
        type="button"
        onClick={() => {
          localStorage.removeItem('bs_user');
          localStorage.removeItem('bs_token');
          window.location.href = '/';
        }}
      >退出登录</button>
    </div>
  );
}