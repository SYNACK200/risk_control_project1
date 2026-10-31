import { useState } from 'react';
import { Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { AnnotatePage } from './pages/Annotate';
import { TaskListPage } from './pages/TaskListPage';
import { EntitiesPage } from './pages/EntitiesPage';
import { ThresholdsPage } from './pages/ThresholdsPage';
import { TemplateAdmin } from './components/TemplateAdmin';
import { ReportView } from './components/ReportView';

function Home() {
  const [tab, setTab] = useState<'tasks' | 'entities' | 'thresholds' | 'annotate' | 'templates'>('tasks');
  return (
    <div className="app">
      <div className="topbar">
        <h1>智能风控 · 银行侧</h1>
        <div className="tabs">
          <button className={tab === 'tasks' ? 'active' : ''} onClick={() => setTab('tasks')}>解析结果</button>
          <button className={tab === 'entities' ? 'active' : ''} onClick={() => setTab('entities')}>客户与账户</button>
          <button className={tab === 'thresholds' ? 'active' : ''} onClick={() => setTab('thresholds')}>风控参数</button>
          <button className={tab === 'annotate' ? 'active' : ''} onClick={() => setTab('annotate')}>模板标注</button>
          <button className={tab === 'templates' ? 'active' : ''} onClick={() => setTab('templates')}>模板管理</button>
        </div>
      </div>
      {tab === 'tasks' && <TaskListPage />}
      {tab === 'entities' && <EntitiesPage />}
      {tab === 'thresholds' && <ThresholdsPage />}
      {tab === 'annotate' && <AnnotatePage />}
      {tab === 'templates' && <TemplateAdmin />}
    </div>
  );
}

function ReportPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const taskId = Number(id);
  return (
    <div className="app">
      <div className="topbar">
        <h1>智能风控 · 银行侧</h1>
        <div className="tabs">
          <button className="active">报告 · 任务 {Number.isFinite(taskId) ? taskId : '—'}</button>
          <button onClick={() => navigate('/')}>返回列表</button>
        </div>
      </div>
      {Number.isFinite(taskId) ? <ReportView taskId={taskId} /> : <p className="muted">报告编号无效。</p>}
    </div>
  );
}

export default function App() {
  return (
    <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/report/:id" element={<ReportPage />} />
      <Route path="*" element={<Home />} />
    </Routes>
  );
}
