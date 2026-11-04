import { Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { AnnotatePage } from './pages/Annotate';
import { TaskListPage } from './pages/TaskListPage';
import { EntitiesPage } from './pages/EntitiesPage';
import { ThresholdsPage } from './pages/ThresholdsPage';
import { TemplateAdmin } from './components/TemplateAdmin';
import { TemplateDetailPage } from './pages/TemplateDetailPage';
import { MetricDefsPage } from './pages/MetricDefsPage';
import { VerificationDefsPage } from './pages/VerificationDefsPage';
import { AuditPage } from './pages/AuditPage';
import { UsersPage } from './pages/UsersPage';
import { ImportTemplatePage } from './pages/ImportTemplatePage';
import { DashboardPage } from './pages/DashboardPage';
import { ReportView } from './components/ReportView';
import { UserBar } from './components/UserBar';
import { useIsAdmin } from './lib/auth';

type NavItem = { key: string; label: string; desc: string; adminOnly?: boolean };
type NavGroup = { group: string; items: NavItem[] };

/** 左侧栏按业务分组：工作台（看结果）/ 模板（管版式）/ 配置（调参数） */
const NAV: NavGroup[] = [
  {
    group: '工作台',
    items: [
      { key: 'dashboard', label: '业务看板', desc: '库内流水汇总与钻取' },
      { key: 'tasks', label: '解析结果', desc: '任务列表与报告' },
      { key: 'entities', label: '客户与账户', desc: '按客户/账户汇总' },
    ],
  },
  {
    group: '报告与口径',
    items: [
      { key: 'metrics', label: '指标口径', desc: '40 项指标定义' },
      { key: 'verifications', label: '校验项', desc: '识别自检定义' },
    ],
  },
  {
    group: '模板',
    items: [
      { key: 'templates', label: '模板库', desc: '查看、启停、版本' },
      { key: 'annotate', label: '新建模板 ①', desc: '载入样例与预读' },
      { key: 'annotate/mark', label: '新建模板 ②', desc: '标注表格列' },
      { key: 'annotate/check', label: '新建模板 ③', desc: '试解析与保存' },
      { key: 'import', label: '导入模板', desc: '粘贴 JSON 导入' },
    ],
  },
  {
    group: '配置',
    items: [{ key: 'thresholds', label: '判定阈值', desc: '阈值与版本' }],
  },
  {
    group: '系统',
    items: [
      { key: 'audit', label: '审计日志', desc: '谁改了什么', adminOnly: true },
      { key: 'users', label: '账号', desc: '银行侧与借款侧账号', adminOnly: true },
    ],
  },
];

const KEYS = NAV.flatMap(g => g.items.map(i => i.key));

function Shell({ active, children }: { active: string; children: React.ReactNode }) {
  const navigate = useNavigate();
  const isAdmin = useIsAdmin();
  const groups = NAV.map(g => ({ ...g, items: g.items.filter(i => !i.adminOnly || isAdmin) }))
    .filter(g => g.items.length > 0);
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="side-brand">
          <div className="side-title">智能风控</div>
          <div className="side-sub">银行侧</div>
        </div>
        <nav className="side-nav">
          {groups.map(group => (
            <div className="nav-group" key={group.group}>
              <div className="nav-title">{group.group}</div>
              {group.items.map(item => (
                <button
                  key={item.key}
                  type="button"
                  className={'nav-item' + (active === item.key ? ' active' : '')}
                  onClick={() => navigate('/' + item.key)}
                  title={item.desc}
                >
                  <span className="nav-label">{item.label}</span>
                  <span className="nav-desc">{item.desc}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="side-foot">
          <button type="button" className="nav-item" onClick={() => navigate('/tasks')}>
            <span className="nav-label">返回解析结果</span>
          </button>
          <UserBar />
        </div>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}

function Home() {
  const location = useLocation();
  const current = location.pathname.replace(/^\//, '');
  const root = current.split('/')[0]; // /annotate/mark 这类多段路径，按首段归到 annotate
  const tab = KEYS.includes(root) ? root : 'tasks';
  // 导航高亮：多段 key（annotate/mark）按完整路径匹配，其余按首段
  const activeKey = KEYS.includes(current) ? current : tab;
  return (
    <Shell active={activeKey}>
      {tab === 'dashboard' && <DashboardPage />}
      {tab === 'tasks' && <TaskListPage />}
      {tab === 'entities' && <EntitiesPage />}
      {tab === 'thresholds' && <ThresholdsPage />}
      {tab === 'annotate' && <AnnotatePage />}
      {tab === 'templates' && <TemplateAdmin />}
      {tab === 'metrics' && <MetricDefsPage />}
      {tab === 'verifications' && <VerificationDefsPage />}
      {tab === 'audit' && <AuditPage />}
      {tab === 'users' && <UsersPage />}
      {tab === 'import' && <ImportTemplatePage />}
    </Shell>
  );
}

function TemplateDetailShell() {
  return (
    <Shell active="templates">
      <TemplateDetailPage />
    </Shell>
  );
}

function ReportPage() {
  const { id } = useParams();
  const taskId = Number(id);
  return (
    <Shell active="tasks">
      {Number.isFinite(taskId) ? <ReportView taskId={taskId} /> : <p className="muted">报告编号无效。</p>}
    </Shell>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/:tab" element={<Home />} />
      <Route path="/annotate/*" element={<Home />} />
      <Route path="/templates/:id" element={<TemplateDetailShell />} />
      <Route path="/report/:id" element={<ReportPage />} />
      <Route path="*" element={<Home />} />
    </Routes>
  );
}