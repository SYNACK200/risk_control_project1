import { Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { AnnotatePage } from './pages/Annotate';
import { TaskListPage } from './pages/TaskListPage';
import { EntitiesPage } from './pages/EntitiesPage';
import { ThresholdsPage } from './pages/ThresholdsPage';
import { TemplateAdmin } from './components/TemplateAdmin';
import { ReportView } from './components/ReportView';

type NavItem = { key: string; label: string; desc: string };
type NavGroup = { group: string; items: NavItem[] };

/** 左侧栏按业务分组：工作台（看结果）/ 模板（管版式）/ 配置（调参数） */
const NAV: NavGroup[] = [
  {
    group: '工作台',
    items: [
      { key: 'tasks', label: '解析结果', desc: '任务列表与报告' },
      { key: 'entities', label: '客户与账户', desc: '按客户与账户汇总' },
    ],
  },
  {
    group: '模板',
    items: [
      { key: 'templates', label: '模板库', desc: '查看、启停、版本' },
      { key: 'annotate', label: '新建模板', desc: '标注样例并外推' },
    ],
  },
  {
    group: '配置',
    items: [{ key: 'thresholds', label: '风控参数', desc: '阈值与版本' }],
  },
];

const KEYS = NAV.flatMap(g => g.items.map(i => i.key));

function Shell({ active, children }: { active: string; children: React.ReactNode }) {
  const navigate = useNavigate();
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="side-brand">
          <div className="side-title">智能风控</div>
          <div className="side-sub">银行侧</div>
        </div>
        <nav className="side-nav">
          {NAV.map(group => (
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
        </div>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}

function Home() {
  const location = useLocation();
  const current = location.pathname.replace(/^\//, '');
  const tab = KEYS.includes(current) ? current : 'tasks';
  return (
    <Shell active={tab}>
      {tab === 'tasks' && <TaskListPage />}
      {tab === 'entities' && <EntitiesPage />}
      {tab === 'thresholds' && <ThresholdsPage />}
      {tab === 'annotate' && <AnnotatePage />}
      {tab === 'templates' && <TemplateAdmin />}
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
      <Route path="/report/:id" element={<ReportPage />} />
      <Route path="*" element={<Home />} />
    </Routes>
  );
}
