import { NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { clearSession, getUser } from '../../auth/store';
import HistoryPage from './HistoryPage';
import ProgressPage from './ProgressPage';
import UploadPage from './UploadPage';

/** 借款侧工作台：上传 → 进度 → 补充材料（严格隔离审核结论）。 */
export default function BorrowerApp() {
  const navigate = useNavigate();
  const user = getUser();
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand small">
          <i>风</i>
          <span>银行流水材料提交</span>
        </div>
        <nav className="topnav">
          <NavLink to="/app/upload" className={({ isActive }) => (isActive ? 'active' : '')}>
            上传流水
          </NavLink>
          <NavLink to="/app/tasks" className={({ isActive }) => (isActive ? 'active' : '')}>
            我的提交记录
          </NavLink>
        </nav>
        <div className="topbar-right">
          <span>{user?.display_name || user?.username}</span>
          <button
            className="btn btn-ghost"
            onClick={() => {
              clearSession();
              navigate('/login');
            }}
          >
            退出
          </button>
        </div>
      </header>
      <main className="content">
        <Routes>
          <Route index element={<Navigate to="upload" replace />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="tasks" element={<HistoryPage />} />
          <Route path="tasks/:id" element={<ProgressPage />} />
          <Route path="*" element={<Navigate to="upload" replace />} />
        </Routes>
      </main>
    </div>
  );
}
