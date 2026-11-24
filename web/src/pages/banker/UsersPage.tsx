import { useCallback, useEffect, useState } from 'react';
import {
  changePassword,
  createUser,
  disableUser,
  enableUser,
  listUsers,
  updateUser,
  type AppUser,
} from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { getUser } from '../../auth/store';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';

export default function UsersPage() {
  const me = getUser();
  const isAdmin = Boolean(me?.is_admin);

  const [rows, setRows] = useState<AppUser[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  // 新建银行员工
  const [createOpen, setCreateOpen] = useState(false);
  const [newUsername, setNewUsername] = useState('');
  const [newDisplay, setNewDisplay] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newIsAdmin, setNewIsAdmin] = useState(false);

  // 重置某用户密码
  const [resetUserId, setResetUserId] = useState<number | null>(null);
  const [resetPwdVal, setResetPwdVal] = useState('');

  // 修改当前登录账号密码
  const [oldPwd, setOldPwd] = useState('');
  const [myNewPwd, setMyNewPwd] = useState('');

  const load = useCallback(() => {
    listUsers()
      .then((data) => setRows(data.items || []))
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreate() {
    if (!newUsername.trim() || newPassword.length < 6) {
      setError('请填写用户名及至少 6 位初始密码。');
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await createUser({
        username: newUsername.trim(),
        password: newPassword,
        display_name: newDisplay.trim() || undefined,
        is_admin: newIsAdmin,
      });
      setCreateOpen(false);
      setNewUsername('');
      setNewDisplay('');
      setNewPassword('');
      setNewIsAdmin(false);
      setNotice('已创建银行侧账号。');
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  async function toggleAdmin(u: AppUser) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await updateUser(u.id, { is_admin: !u.is_admin });
      setNotice(`已更新 ${u.username} 的管理员权限。`);
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  async function toggleStatus(u: AppUser) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      if (u.status === 'active') {
        await disableUser(u.id);
        setNotice(`已停用账号 ${u.username}。`);
      } else {
        await enableUser(u.id);
        setNotice(`已恢复启用账号 ${u.username}。`);
      }
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  async function submitResetPwd() {
    if (!resetUserId || resetPwdVal.length < 6) {
      setError('新密码至少需要 6 位。');
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await updateUser(resetUserId, { password: resetPwdVal });
      setResetUserId(null);
      setResetPwdVal('');
      setNotice('已完成密码重置。');
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  async function submitChangeMyPwd() {
    if (!oldPwd || myNewPwd.length < 6) {
      setError('请填写原密码及至少 6 位新密码。');
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await changePassword(oldPwd, myNewPwd);
      setOldPwd('');
      setMyNewPwd('');
      setNotice('当前账号密码已修改。');
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>账号与权限管理</h1>
          <p className="sub">借款人可自助注册；银行员工与管理员账号由管理员创建、赋权、启停及重置密码。</p>
        </div>
        {isAdmin && (
          <Button size="sm" onClick={() => setCreateOpen((v) => !v)}>
            {createOpen ? '收起新建表单' : '+ 新建银行账号'}
          </Button>
        )}
      </header>

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="ok">{notice}</Notice> : null}

      {isAdmin && createOpen && (
        <section className="import-box">
          <strong>创建银行侧员工 / 管理员账号</strong>
          <div className="filters" style={{ marginTop: 10 }}>
            <input
              type="text"
              placeholder="登录用户名"
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
            />
            <input
              type="text"
              placeholder="姓名 / 显示名称（可选）"
              value={newDisplay}
              onChange={(e) => setNewDisplay(e.target.value)}
            />
            <input
              type="password"
              placeholder="初始密码（≥6位）"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
            <label className="inline-toggle small">
              <input
                type="checkbox"
                checked={newIsAdmin}
                onChange={(e) => setNewIsAdmin(e.target.checked)}
              />
              设为管理员
            </label>
            <Button size="sm" disabled={busy} onClick={() => void handleCreate()}>
              创建账号
            </Button>
          </div>
        </section>
      )}

      <table className="grid compact">
        <thead>
          <tr>
            <th>用户名</th>
            <th>显示名</th>
            <th>角色</th>
            <th>状态</th>
            <th>最近登录</th>
            {isAdmin && <th>管理操作</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((user) => (
            <tr key={user.id}>
              <td className="mono">{user.username}</td>
              <td>{user.display_name ?? '—'}</td>
              <td>
                <span className={'pill ' + (user.is_admin ? 'ok' : '')}>
                  {user.role === 'banker' ? (user.is_admin ? '银行管理员' : '银行员工') : '借款人'}
                </span>
              </td>
              <td>
                <span className={'pill ' + (user.status === 'active' ? 'ok' : 'err')}>
                  {user.status === 'active' ? '正常' : '已停用'}
                </span>
              </td>
              <td className="small muted">
                {user.last_login_at ? new Date(user.last_login_at).toLocaleString() : '—'}
              </td>
              {isAdmin && (
                <td className="actions-cell">
                  {user.role === 'banker' && (
                    <button type="button" className="link-btn" disabled={busy} onClick={() => void toggleAdmin(user)}>
                      {user.is_admin ? '取消管理员' : '设为管理员'}
                    </button>
                  )}
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => {
                      setResetUserId(user.id);
                      setResetPwdVal('');
                    }}
                  >
                    重置密码
                  </button>
                  {user.id !== me?.id && (
                    <button
                      type="button"
                      className={'link-btn ' + (user.status === 'active' ? 'danger' : '')}
                      disabled={busy}
                      onClick={() => void toggleStatus(user)}
                    >
                      {user.status === 'active' ? '停用' : '启用'}
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      {isAdmin && resetUserId !== null && (
        <div className="import-box" style={{ marginTop: 14 }}>
          <strong>重置用户 #{resetUserId} 的登录密码</strong>
          <div className="filters" style={{ marginTop: 8 }}>
            <input
              type="password"
              placeholder="输入新密码（≥6位）"
              value={resetPwdVal}
              onChange={(e) => setResetPwdVal(e.target.value)}
            />
            <Button size="sm" disabled={busy} onClick={() => void submitResetPwd()}>确认重置</Button>
            <Button size="sm" variant="ghost" onClick={() => setResetUserId(null)}>取消</Button>
          </div>
        </div>
      )}

      <section className="import-box" style={{ marginTop: 22 }}>
        <h2>修改我的登录密码（{me?.username}）</h2>
        <div className="filters">
          <input
            type="password"
            placeholder="当前密码"
            value={oldPwd}
            onChange={(e) => setOldPwd(e.target.value)}
          />
          <input
            type="password"
            placeholder="新密码（至少6位）"
            value={myNewPwd}
            onChange={(e) => setMyNewPwd(e.target.value)}
          />
          <Button size="sm" disabled={busy} onClick={() => void submitChangeMyPwd()}>
            更新密码
          </Button>
        </div>
      </section>
    </div>
  );
}
