import { Navigate, NavLink, Route, Routes, useNavigate } from 'react-router-dom';
import ErrorBoundary from '../../ui/ErrorBoundary';
import { clearSession, getUser } from '../../auth/store';
import TaskListPage from './TaskListPage';
import QueuePage from './QueuePage';
import ReportPage from './ReportPage';
import AuditPage from './AuditPage';
import UsersPage from './UsersPage';
import AnnotatePage from './AnnotatePage';
import LabPage from './LabPage';
import ThresholdsPage from './ThresholdsPage';
import EntitiesPage from './EntitiesPage';
import OcrRoutingPage from './OcrRoutingPage';
import TemplatesPage from './TemplatesPage';
import TemplateDetailPage from './TemplateDetailPage';
import TemplateLayoutPage from './TemplateLayoutPage';
import DashboardPage from './DashboardPage';
import GlossaryPage from './GlossaryPage';
import MetricDefsPage from './MetricDefsPage';
import VerificationDefsPage from './VerificationDefsPage';

/**
 * 银行侧工作台。
 *
 * 侧栏按「受理与报告 / 模板 / 参数 / 系统」分组，和旧版的信息架构保持一致——
 * 客户经理的心智模型是按任务走的，不是按功能表走的。
 *
 * 所有核心银行侧页面已合入单一 SPA，并保留规范路由别名兼容旧书签。
 */
export default function BankerApp() {
  const navigate = useNavigate();
  const user = getUser();
  const isAdmin = Boolean(user?.is_admin);

  return (
    <div className="shell with-sider">
      <header className="topbar">
        <div className="brand small">
          <i>风</i>
          <span>银行工作台</span>
        </div>
        <div className="topbar-right">
          <span>
            {user?.display_name || user?.username}
            {isAdmin ? ' · 管理员' : ''}
          </span>
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

      <div className="body">
        <nav className="sider">
          <div className="sider-group">
            <span className="sider-title">受理与报告</span>
            <NavLink to="/bank" end>看板</NavLink>
            <NavLink to="/bank/tasks">任务与报告</NavLink>
            <NavLink to="/bank/queue">任务队列</NavLink>
          </div>
          <div className="sider-group">
            <span className="sider-title">模板</span>
            <NavLink to="/bank/templates" end>模板库</NavLink>
            <NavLink to="/bank/annotate">标注</NavLink>
          </div>
          <div className="sider-group">
            <span className="sider-title">参数</span>
            <NavLink to="/bank/lab">特征 Lab</NavLink>
            <NavLink to="/bank/thresholds">风控参数</NavLink>
            <NavLink to="/bank/entities">客户与账户</NavLink>
            <NavLink to="/bank/ocr">OCR 路由</NavLink>
          </div>
          <div className="sider-group">
            <span className="sider-title">系统</span>
            <NavLink to="/bank/metrics">自定义口径</NavLink>
            <NavLink to="/bank/verifications">核验口径字典</NavLink>
            <NavLink to="/bank/glossary">口径说明</NavLink>
            {isAdmin ? <NavLink to="/bank/audit">操作审计</NavLink> : null}
            {isAdmin ? <NavLink to="/bank/users">账号</NavLink> : null}
          </div>
        </nav>

        <main className="content">
          <ErrorBoundary>
          <Routes>
            <Route index element={<DashboardPage />} />
            <Route path="tasks" element={<TaskListPage />} />
            <Route path="queue" element={<QueuePage />} />
            <Route path="report/:id" element={<ReportPage />} />
            <Route path="annotate" element={<AnnotatePage />} />
            <Route path="annotate/*" element={<AnnotatePage />} />
            <Route path="templates" element={<TemplatesPage />} />
            <Route path="templates/:id" element={<TemplateDetailPage />} />
            <Route path="templates/:id/layout" element={<TemplateLayoutPage />} />
            <Route path="lab" element={<LabPage />} />
            <Route path="thresholds" element={<ThresholdsPage />} />
            <Route path="entities" element={<EntitiesPage />} />
            <Route path="ocr" element={<OcrRoutingPage />} />
            <Route path="glossary" element={<GlossaryPage />} />
            <Route path="metrics" element={<MetricDefsPage />} />
            <Route path="verifications" element={<VerificationDefsPage />} />
            <Route path="audit" element={isAdmin ? <AuditPage /> : <Navigate to="/bank" replace />} />
            <Route path="users" element={isAdmin ? <UsersPage /> : <Navigate to="/bank" replace />} />
            {/* 规范路由与旧书签别名兼容 */}
            <Route path="dashboard" element={<Navigate to="/bank" replace />} />
            <Route path="ocr-routing" element={<Navigate to="/bank/ocr" replace />} />
            <Route path="metric-defs" element={<Navigate to="/bank/metrics" replace />} />
            <Route path="verification-defs" element={<Navigate to="/bank/verifications" replace />} />
            <Route path="import" element={<Navigate to="/bank/templates" replace />} />
            <Route path="import-template" element={<Navigate to="/bank/templates" replace />} />
            <Route
              path="*"
              element={
                <div className="panel">
                  <h1>页面不存在</h1>
                  <p className="sub">未找到对应的工作台地址，请返回看板重新进入。</p>
                  <button type="button" className="btn" onClick={() => navigate('/bank')}>返回看板</button>
                </div>
              }
            />
          </Routes>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
