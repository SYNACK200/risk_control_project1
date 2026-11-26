import { Navigate, NavLink, Route, Routes, useNavigate } from 'react-router-dom';
import ErrorBoundary from '../../ui/ErrorBoundary';
import { clearSession, getUser } from '../../auth/store';
import { useLabHealth } from '../../hooks/useLabHealth';
import TaskListPage from './TaskListPage';
import ReportPage from './ReportPage';
import AuditPage from './AuditPage';
import UsersPage from './UsersPage';
import AnnotatePage from './AnnotatePage';
import FeaturesPage from './FeaturesPage';
import ThresholdsPage from './ThresholdsPage';
import EntitiesPage from './EntitiesPage';
import OcrRoutingPage from './OcrRoutingPage';
import TemplatesPage from './TemplatesPage';
import TemplateDetailPage from './TemplateDetailPage';
import TemplateLayoutPage from './TemplateLayoutPage';
import DashboardPage from './DashboardPage';
import DefinitionsPage from './DefinitionsPage';
import NotFoundPage from './NotFoundPage';

type NavItem = { label: string; to: string; end?: boolean; admin?: boolean };

/** 银行侧信息架构的唯一来源：侧栏、404 入口列表都从这里出。新增页面先在这里定归属。 */
const NAV: { title: string; items: NavItem[] }[] = [
  {
    title: '受理',
    items: [
      { label: '看板', to: '/bank', end: true },
      { label: '任务中心', to: '/bank/tasks' },
      { label: '客户与账户', to: '/bank/entities' },
    ],
  },
  {
    title: '模板',
    items: [
      { label: '模板库', to: '/bank/templates' },
      { label: '标注工作台', to: '/bank/annotate' },
    ],
  },
  {
    title: '口径',
    items: [
      { label: '口径中心', to: '/bank/definitions' },
      { label: '风控参数', to: '/bank/thresholds' },
    ],
  },
  {
    title: '特征',
    items: [{ label: '特征平台', to: '/bank/features' }],
  },
  {
    title: '系统',
    items: [
      { label: 'OCR 路由', to: '/bank/ocr' },
      { label: '操作审计', to: '/bank/audit', admin: true },
      { label: '账号', to: '/bank/users', admin: true },
    ],
  },
];

/** 旧书签与旧链接的全部落点：只做重定向，不许出现 404。 */
const LEGACY_REDIRECTS: { from: string; to: string }[] = [
  { from: 'dashboard', to: '/bank' },
  { from: 'queue', to: '/bank/tasks?tab=queue' },
  { from: 'metrics', to: '/bank/definitions?tab=metric' },
  { from: 'metric-defs', to: '/bank/definitions?tab=metric' },
  { from: 'verifications', to: '/bank/definitions?tab=verification' },
  { from: 'verification-defs', to: '/bank/definitions?tab=verification' },
  { from: 'glossary', to: '/bank/definitions?tab=glossary' },
  { from: 'lab', to: '/bank/features' },
  { from: 'ocr-routing', to: '/bank/ocr' },
  { from: 'import', to: '/bank/templates' },
  { from: 'import-template', to: '/bank/templates' },
];

/**
 * 银行侧工作台。
 *
 * 侧栏按「受理 / 模板 / 口径 / 特征 / 系统」五组划分，归属以 docs/前端信息架构.md 为准。
 */
export default function BankerApp() {
  const navigate = useNavigate();
  const user = getUser();
  const isAdmin = Boolean(user?.is_admin);
  const lab = useLabHealth();

  const groups = NAV.map((group) => ({
    title: group.title,
    items: group.items.filter((item) => !item.admin || isAdmin),
  })).filter((group) => group.items.length > 0);

  const labUp = lab.status === 'up';

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
        <nav className="sider" aria-label="银行侧导航">
          <div className="sider-groups">
            {groups.map((group) => (
              <div className="sider-group" key={group.title}>
                <span className="sider-title">{group.title}</span>
                {group.items.map((item) => (
                  <NavLink key={item.to} to={item.to} end={item.end}>
                    {item.label}
                  </NavLink>
                ))}
              </div>
            ))}
          </div>
          <div
            className="sider-foot"
            title={labUp ? `特征服务目录版本 ${lab.version ?? '—'}` : '业务后端没有连上特征服务'}
          >
            <span className={'status-dot ' + (labUp ? 'ok' : lab.status === 'checking' ? '' : 'bad')} />
            特征平台：{labUp ? '运行中' : lab.status === 'checking' ? '检测中' : '未连接'}
          </div>
        </nav>

        <main className="content">
          <ErrorBoundary>
          <Routes>
            <Route index element={<DashboardPage />} />
            <Route path="tasks" element={<TaskListPage />} />
            <Route path="report/:id" element={<ReportPage />} />
            <Route path="annotate" element={<AnnotatePage />} />
            <Route path="annotate/*" element={<AnnotatePage />} />
            <Route path="templates" element={<TemplatesPage />} />
            <Route path="templates/:id" element={<TemplateDetailPage />} />
            <Route path="templates/:id/layout" element={<TemplateLayoutPage />} />
            <Route path="definitions" element={<DefinitionsPage />} />
            <Route path="thresholds" element={<ThresholdsPage />} />
            <Route path="entities" element={<EntitiesPage />} />
            <Route path="features" element={<FeaturesPage />} />
            <Route path="ocr" element={<OcrRoutingPage />} />
            <Route path="audit" element={isAdmin ? <AuditPage /> : <Navigate to="/bank" replace />} />
            <Route path="users" element={isAdmin ? <UsersPage /> : <Navigate to="/bank" replace />} />
            {LEGACY_REDIRECTS.map((redirect) => (
              <Route key={redirect.from} path={redirect.from} element={<Navigate to={redirect.to} replace />} />
            ))}
            <Route path="*" element={<NotFoundPage groups={groups} />} />
          </Routes>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
