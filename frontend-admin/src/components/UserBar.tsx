import { useMe } from '../lib/auth';

/** 侧栏底部用户区：身份、角色徽标、退出。 */
export function UserBar() {
  const me = useMe();
  if (!me) return null;

  // 只标权限级别，不标账号属于哪一侧——屏幕上不需要出现「你是什么身份」这类可被旁观者读到的信息
  const roleText = me.is_admin ? '管理员' : '员工';

  return (
    <div className="side-user">
      <div className="side-user-main">
        <span className="side-user-avatar">{(me.display_name || me.username || '?').slice(0, 1).toUpperCase()}</span>
        <div className="side-user-info">
          <span className="side-user-name">{me.display_name || me.username}</span>
          <span className={'side-user-role' + (me.is_admin ? ' is-admin' : '')}>{roleText}</span>
        </div>
      </div>
      <button
        className="side-user-logout"
        type="button"
        title="退出登录"
        onClick={() => {
          localStorage.removeItem('bs_user');
          localStorage.removeItem('bs_token');
          window.location.href = '/';
        }}
      >退出登录</button>
    </div>
  );
}