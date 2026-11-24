import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getDashboard, type DashboardData } from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { Notice } from '../../ui/Notice';
import { Bar } from '../../components/ReportCharts';

/**
 * 看板：一批流水进来之后，先看这里再看单份报告。
 *
 * 关心四件事：量（受理多少、多少笔）、质（通过/存疑/失败）、哪家银行在出问题、
 * 哪些风险规则在反复命中。单份报告回答「这一户能不能放」，看板回答「这批件整体什么情况」。
 */
export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    getDashboard()
      .then(setData)
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  }, []);

  if (error) return <div className="panel"><Notice>{error}</Notice></div>;
  if (!data) return <p className="muted">加载中…</p>;

  const s = data.summary;
  const maxVerdict = Math.max(...data.verdicts.map((item) => item.count), 1);
  const maxHit = Math.max(...data.threshold_hits.map((item) => item.count), 1);

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>看板</h1>
          <p className="sub">
            当前参数版本 v{s.threshold_version}；阈值改了只影响之后的分析，历史报告按各自版本解释。
          </p>
        </div>
        <Link className="btn btn-ghost" to="/bank/tasks">去任务与报告</Link>
      </header>

      <section className="gauge-row">
        <div className="gauge-card">
          <h3>受理任务</h3>
          <span className="score-value">{s.tasks}</span>
          <span className="muted small">完成 {s.done} · 失败 {s.failed}</span>
        </div>
        <div className="gauge-card">
          <h3>流水笔数</h3>
          <span className="score-value">{s.txn_total}</span>
          <span className="muted small">平均 {s.avg_txn} 笔/份</span>
        </div>
        <div className="gauge-card">
          <h3>达标率</h3>
          <span className="score-value">{s.tasks ? Math.round((s.done / s.tasks) * 100) : 0}%</span>
          <span className="muted small">解析覆盖率告警 {s.coverage_warn} 份</span>
        </div>
        <div className="gauge-card">
          <h3>自定义指标</h3>
          <span className="score-value">{s.custom_metrics}</span>
          <span className="muted small">有值的自定义指标项</span>
        </div>
      </section>

      <section>
        <h2>结论分布</h2>
        <table className="grid compact">
          <tbody>
            {data.verdicts.map((item) => (
              <tr key={item.verdict}>
                <td style={{ width: 160 }}>
                  <Link className="link-btn" to={'/bank/tasks?q=' + encodeURIComponent(item.verdict)}>
                    {item.verdict}
                  </Link>
                </td>
                <td>
                  <span className="bar-inline">
                    <Bar value={item.count} max={maxVerdict} tone={item.verdict === '未发现异常' || item.verdict.includes('通过') ? 'brand' : item.verdict.includes('不一致') || item.verdict.includes('可疑') || item.verdict.includes('不通过') ? 'bad' : 'muted'} />
                    <span>{item.count} 份</span>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>等级分布</h2>
        <table className="grid compact">
          <tbody>
            {data.grades.map((item) => (
              <tr key={item.grade}>
                <td style={{ width: 160 }}>{item.label}</td>
                <td>
                  <span className="bar-inline">
                    <Bar value={item.count} max={Math.max(...data.grades.map((g) => g.count), 1)}
                         tone={item.grade === 'good' ? 'brand' : item.grade === 'fair' ? 'warn' : 'muted'} />
                    <span>{item.count} 份</span>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>各银行</h2>
        <table className="grid compact">
          <thead><tr><th>银行</th><th>任务</th><th>流水笔数</th></tr></thead>
          <tbody>
            {data.banks.map((item) => (
              <tr key={item.bank_code}>
                <td>
                  <Link className="link-btn" to={'/bank/tasks?bank=' + encodeURIComponent(item.bank_code)}>
                    {item.bank_code}
                  </Link>
                </td>
                <td>{item.tasks}</td>
                <td className="small muted">{item.txn}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">「未识别」多说明这些件的银行名不在正文里，也没有对应模板——先把模板补上再看分布。</p>
      </section>

      <section>
        <h2>风险命中排行</h2>
        {data.threshold_hits.length ? (
          <table className="grid compact">
            <thead><tr><th>规则</th><th>命中份数</th><th>由哪个参数触发</th></tr></thead>
            <tbody>
              {data.threshold_hits.map((item) => (
                <tr key={item.code}>
                  <td>
                    <Link className="link-btn" to={'/bank/tasks?risk_code=' + encodeURIComponent(item.code)}>
                      {item.code} {item.name ? `· ${item.name}` : ''}
                    </Link>
                  </td>
                  <td>
                    <span className="bar-inline">
                      <Bar value={item.count} max={maxHit} tone="warn" />
                      <span>{item.count}</span>
                    </span>
                  </td>
                  <td className="small muted">
                    {item.threshold_key ? (
                      <Link className="link-btn" to={`/bank/thresholds#def-${item.threshold_key}`}>
                        {item.threshold_key}
                      </Link>
                    ) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted small">还没有命中记录。</p>}
      </section>

      <section>
        <h2>最近受理</h2>
        <table className="grid compact">
          <thead><tr><th>业务号</th><th>状态</th><th>结论</th><th>得分</th><th>笔数</th></tr></thead>
          <tbody>
            {data.recent.map((item) => (
              <tr key={item.task_id}>
                <td><Link className="link-btn" to={'/bank/report/' + item.task_id}>{item.biz_no}</Link></td>
                <td className="small">{{ DONE: '已完成', FAILED: '失败', QUEUED: '排队中', PARSING: '解析中', CHECKING: '预检中', VERIFYING: '核验中', REPORTING: '生成中', NEED_SUPPLEMENT: '待补传' }[item.status] ?? item.status}</td>
                <td className="small">{item.verdict ?? '—'}</td>
                <td className="small">{item.overall ?? '—'}</td>
                <td className="small muted">{item.txn_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
