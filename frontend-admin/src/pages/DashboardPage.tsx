import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getDashboard, type DashboardData } from '../lib/api';

/** 业务看板：先用一句话说清现状，再给结构化分布，最后才是明细表。 */
export function DashboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => {
    setLoading(true);
    getDashboard()
      .then(d => { setData(d); setError(''); })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  const graded = useMemo(() => (data?.grades ?? []).reduce((n, g) => n + g.count, 0), [data]);
  const verdictTotal = useMemo(() => (data?.verdicts ?? []).reduce((n, v) => n + v.count, 0), [data]);
  const good = useMemo(() => (data?.grades ?? []).find(g => g.grade === 'good')?.count ?? 0, [data]);
  const risk = useMemo(
    () => (data?.verdicts ?? []).filter(v => v.verdict !== '未发现异常').reduce((n, v) => n + v.count, 0),
    [data],
  );

  if (loading) return <div className="result"><p className="muted">正在汇总…</p></div>;
  if (!data) return <div className="result">{error && <div className="notice error">{error}</div>}</div>;

  const s = data.summary;
  const goodPct = graded ? Math.round((good / graded) * 100) : 0;
  const maxVerdict = Math.max(1, ...data.verdicts.map(v => v.count));
  const bankTotal = data.banks.reduce((n, b) => n + b.tasks, 0);

  return (
    <div className="result dash">
      <div className="dash-head">
        <div>
          <h2>业务看板</h2>
          <p className="dash-lead">
            库里共 <b>{s.tasks}</b> 份流水、<b>{s.txn_total.toLocaleString()}</b> 笔；
            已出报告 {graded} 份，其中良好 <b>{good}</b> 份（<b>{goodPct}%</b>），
            {risk > 0 ? <>需关注 <b className="dash-warn">{risk}</b> 份。</> : <>没有需关注的结论。</>}
          </p>
        </div>
        <button className="pill-btn" type="button" onClick={() => setHelpOpen(v => !v)}>指标口径说明</button>
      </div>

      {helpOpen && (
        <div className="notice info dash-help">
          任务数=未删除任务；笔数=解析出的流水行数；评分与结论取每份任务的最新报告；
          覆盖率告警=受理时解析笔数明显少于文件声明（门禁：页脚比对 &lt;80%，或每页 &lt;2 笔）；
          阈值版本=生成这些报告时生效的判定阈值版本。点任意卡片或表格行可钻进明细。
          <button className="notice-close" type="button" onClick={() => setHelpOpen(false)}>×</button>
        </div>
      )}

      {error && <div className="notice error">{error}</div>}

      <div className="dash-kpis">
        <button className="dash-kpi" type="button" onClick={() => navigate('/tasks')}>
          <span className="dash-kpi-value">{s.tasks}</span>
          <span className="dash-kpi-label">受理任务</span>
          <span className="dash-kpi-sub">完成 {s.done} · 失败 {s.failed > 0 ? <b className="dash-warn">{s.failed}</b> : 0}</span>
        </button>
        <button className="dash-kpi" type="button" onClick={() => navigate('/entities')}>
          <span className="dash-kpi-value">{s.txn_total.toLocaleString()}</span>
          <span className="dash-kpi-label">流水笔数</span>
          <span className="dash-kpi-sub">平均 {s.avg_txn} 笔/份</span>
        </button>
        <button className={'dash-kpi' + (s.coverage_warn > 0 ? ' is-alert' : '')} type="button" onClick={() => navigate('/tasks')}>
          <span className="dash-kpi-value">{s.coverage_warn}</span>
          <span className="dash-kpi-label">解析不完整</span>
          <span className="dash-kpi-sub">覆盖率 &lt; 80% 或每页 &lt; 2 笔</span>
        </button>
        <button className="dash-kpi" type="button" onClick={() => navigate('/thresholds')}>
          <span className="dash-kpi-value">v{s.threshold_version ?? '—'}</span>
          <span className="dash-kpi-label">判定阈值版本</span>
          <span className="dash-kpi-sub">点击查看/调整参数</span>
        </button>
      </div>

      <section className="dash-block">
        <div className="dash-block-head">
          <h3>风险等级构成</h3>
          <span className="muted small">{graded} 份报告</span>
        </div>
        <div className="dash-stack">
          {data.grades.map(g => (
            <div key={g.grade}
              className={'dash-stack-seg grade-' + g.grade}
              style={{ flexGrow: g.count }}
              title={g.label + ' ' + g.count + ' 份'}>
              {g.count > 0 && graded > 0 && (g.count / graded) > 0.12 ? g.count : ''}
            </div>
          ))}
          {graded === 0 && <div className="dash-stack-seg grade-empty" style={{ flexGrow: 1 }}>暂无报告</div>}
        </div>
        <div className="dash-legend">
          {data.grades.map(g => (
            <span key={g.grade} className="dash-legend-item">
              <i className={'dash-dot grade-' + g.grade} />
              {g.label} <b>{g.count}</b>
              <span className="muted small">{graded ? Math.round((g.count / graded) * 100) + '%' : ''}</span>
            </span>
          ))}
        </div>
      </section>

      <section className="dash-block">
        <div className="dash-block-head">
          <h3>结论分布</h3>
          <span className="muted small">点击某一项看对应任务</span>
        </div>
        <div className="dash-bars">
          {data.verdicts.map(v => (
            <button key={v.verdict} className="dash-bar-row" type="button"
              onClick={() => navigate('/tasks?verdict=' + encodeURIComponent(v.verdict))}>
              <span className="dash-bar-label">{v.verdict}</span>
              <span className="dash-bar-track">
                <span className={'dash-bar-fill' + (v.verdict === '未发现异常' ? ' ok' : '')}
                  style={{ width: (v.count / maxVerdict) * 100 + '%' }} />
              </span>
              <span className="dash-bar-num">{v.count}</span>
              <span className="dash-bar-pct">{verdictTotal ? Math.round((v.count / verdictTotal) * 100) + '%' : ''}</span>
            </button>
          ))}
          {data.verdicts.length === 0 && <p className="muted">还没有结论。</p>}
        </div>
      </section>

      <div className="dash-cols">
        <section className="dash-block">
          <div className="dash-block-head">
            <h3>按银行</h3>
            <span className="muted small">{bankTotal} 份</span>
          </div>
          <table className="mini dash-table">
            <thead><tr><th>银行</th><th className="num">任务</th><th className="num">笔数</th><th className="num">占比</th></tr></thead>
            <tbody>
              {data.banks.map(b => (
                <tr key={b.bank_code} onClick={() => navigate('/tasks?bank=' + encodeURIComponent(b.bank_code))}>
                  <td className="mono">{b.bank_code}</td>
                  <td className="num">{b.tasks}</td>
                  <td className="num">{b.txn.toLocaleString()}</td>
                  <td className="num muted">{bankTotal ? Math.round((b.tasks / bankTotal) * 100) + '%' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.banks.length === 0 && <p className="muted">还没有数据。</p>}
        </section>

        <section className="dash-block">
          <div className="dash-block-head">
            <h3>阈值命中</h3>
            <span className="muted small">点一行跳到对应阈值参数</span>
          </div>
          <table className="mini dash-table">
            <thead><tr><th>结论</th><th>含义</th><th className="num">命中</th></tr></thead>
            <tbody>
              {data.threshold_hits.map(h => (
                <tr key={h.code} onClick={() => navigate('/thresholds' + (h.threshold_key ? '#def-' + h.threshold_key : ''))}>
                  <td className="mono">{h.code}</td>
                  <td>{h.name}</td>
                  <td className="num">{h.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.threshold_hits.length === 0 && <p className="muted">目前没有命中的风险结论。</p>}
        </section>
      </div>

      <section className="dash-block">
        <div className="dash-block-head">
          <h3>最近 10 份</h3>
          <span className="muted small">点一行看报告</span>
        </div>
        <table className="mini dash-table">
          <thead><tr><th>任务</th><th>状态</th><th>银行</th><th className="num">笔数</th><th className="num">评分</th><th>结论</th></tr></thead>
          <tbody>
            {data.recent.map(r => (
              <tr key={r.task_id} onClick={() => navigate('/report/' + r.task_id)}>
                <td className="mono">#{r.task_id}</td>
                <td className="muted small">{r.status}</td>
                <td className="mono small">{r.bank_code ?? '—'}</td>
                <td className="num">{r.txn_count}</td>
                <td className="num">{r.overall === null ? '—' : r.overall}</td>
                <td className="muted small">{r.verdict ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.recent.length === 0 && <p className="muted">还没有任务。</p>}
      </section>
    </div>
  );
}
