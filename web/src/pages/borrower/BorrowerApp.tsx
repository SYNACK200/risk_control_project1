import { Navigate, NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { clearSession, getUser } from '../../auth/store';
import ProgressHubPage from './ProgressHubPage';
import UploadPage from './UploadPage';

/** 旧链接 /app/tasks/:id → /app/progress/:id */
function LegacyTaskRedirect() {
  const { id } = useParams();
  return <Navigate to={'/app/progress/' + (id ?? '')} replace />;
}

/**
 * 借款侧工作台：上传 → 进度（当前 / 历史）。
 * 严格隔离审核结论：借款人只看得到收件与处理状态。
 */
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
        <nav className="topnav" aria-label="借款侧导航">
          <NavLink to="/app" end className={({ isActive }) => (isActive ? 'active' : '')}>
            上传流水
          </NavLink>
          <NavLink to="/app/progress" className={({ isActive }) => (isActive ? 'active' : '')}>
            处理进度
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
          <Route index element={<UploadPage />} />
          <Route path="progress/:id?" element={<ProgressHubPage />} />
          {/* 旧书签兼容：全部重定向，不许 404 */}
          <Route path="upload" element={<Navigate to="/app" replace />} />
          <Route path="history" element={<Navigate to="/app/progress?tab=history" replace />} />
          <Route path="tasks" element={<Navigate to="/app/progress?tab=history" replace />} />
          <Route path="tasks/:id" element={<LegacyTaskRedirect />} />
          <Route path="*" element={<Navigate to="/app" replace />} />
        </Routes>
      </main>
    </div>
  );
}
