import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getDashboard, type DashboardData } from '../lib/api';

/** 业务看板：库里已有流水的总体情况，点击任一项可钻进对应明细。 */
export function DashboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getDashboard()
      .then(d => { setData(d); setError(''); })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  const totalGraded = useMemo(() => (data?.grades ?? []).reduce((n, g) => n + g.count, 0), [data]);
  const maxVerdict = useMemo(() => Math.max(1, ...(data?.verdicts ?? []).map(v => v.count)), [data]);

  if (loading) return <div className="result"><p className="muted">正在汇总…</p></div>;
  if (!data) return <div className="result">{error && <div className="notice error">{error}</div>}</div>;

  const s = data.summary;
  return (
    <div className="result">
      <div className="result-head">
        <h2>业务看板</h2>
        <span className="muted">库里已有流水的汇总 · 点击任意一项可钻取明细</span>
      </div>
      {error && <div className="notice error">{error}</div>}

      <section className="dash-kpis">
        <button className="dash-kpi" type="button" onClick={() => navigate('/tasks')}>
          <span className="dash-kpi-label">已受理任务</span>
          <span className="dash-kpi-value">{s.tasks}</span>
          <span className="dash-kpi-sub">完成 {s.done} · 失败 {s.failed}</span>
        </button>
        <button className="dash-kpi" type="button" onClick={() => navigate('/entities')}>
          <span className="dash-kpi-label">流水总笔数</span>
          <span className="dash-kpi-value">{s.txn_total.toLocaleString()}</span>
          <span className="dash-kpi-sub">平均 {s.avg_txn} 笔/份</span>
        </button>
        <button className="dash-kpi" type="button" onClick={() => navigate('/tasks')}>
          <span className="dash-kpi-label">解析覆盖率告警</span>
          <span className="dash-kpi-value" style={{ color: s.coverage_warn > 0 ? '#e45151' : undefined }}>{s.coverage_warn}</span>
          <span className="dash-kpi-sub">覆盖率 &lt; 80% 或每页 &lt; 2 笔</span>
        </button>
        <button className="dash-kpi" type="button" onClick={() => navigate('/thresholds')}>
          <span className="dash-kpi-label">当前阈值版本</span>
          <span className="dash-kpi-value">v{s.threshold_version ?? '—'}</span>
          <span className="dash-kpi-sub">点此进判定阈值设置</span>
        </button>
      </section>

      <div className="dash-row">
        <section className="card">
          <div className="card-head-static"><strong>风险等级分布</strong><span className="muted small">共 {totalGraded} 份报告</span></div>
          <div className="card-body">
            {data.grades.length === 0 && <p className="muted">还没有报告。</p>}
            {data.grades.map(g => (
              <div className="dash-bar-row" key={g.grade}>
                <span className="dash-bar-label">{g.label}</span>
                <div className="dash-bar-track">
                  <div className={'dash-bar-fill grade-' + g.grade}
                    style={{ width: (totalGraded ? (g.count / totalGraded) * 100 : 0) + '%' }} />
                </div>
                <span className="dash-bar-num">{g.count}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="card">
          <div className="card-head-static"><strong>结论分布</strong><span className="muted small">点击进入任务列表</span></div>
          <div className="card-body">
            {data.verdicts.length === 0 && <p className="muted">还没有结论。</p>}
            {data.verdicts.map(v => (
              <button className="dash-bar-row as-button" key={v.verdict} type="button"
                onClick={() => navigate('/tasks?verdict=' + encodeURIComponent(v.verdict))}>
                <span className="dash-bar-label">{v.verdict}</span>
                <div className="dash-bar-track">
                  <div className="dash-bar-fill" style={{ width: (v.count / maxVerdict) * 100 + '%' }} />
                </div>
                <span className="dash-bar-num">{v.count}</span>
              </button>
            ))}
          </div>
        </section>
      </div>

      <div className="dash-row">
        <section className="card">
          <div className="card-head-static"><strong>按银行</strong><span className="muted small">识别到的开户行</span></div>
          <div className="card-body">
            <table className="mini">
              <thead><tr><th>银行</th><th>任务</th><th>流水笔数</th><th>平均</th></tr></thead>
              <tbody>
                {data.banks.map(b => (
                  <tr key={b.bank_code} className="clickable" onClick={() => navigate('/tasks?bank=' + encodeURIComponent(b.bank_code))}>
                    <td className="mono">{b.bank_code}</td>
                    <td className="num">{b.tasks}</td>
                    <td className="num">{b.txn.toLocaleString()}</td>
                    <td className="num">{b.tasks ? Math.round(b.txn / b.tasks) : 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.banks.length === 0 && <p className="muted">还没有数据。</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-head-static"><strong>阈值命中 Top</strong><span className="muted small">点击进判定阈值设置</span></div>
          <div className="card-body">
            {data.threshold_hits.length === 0
              ? <p className="muted">目前没有命中的风险结论。</p>
              : (
                <table className="mini">
                  <thead><tr><th>结论</th><th>名称</th><th>命中次数</th></tr></thead>
                  <tbody>
                    {data.threshold_hits.map(h => (
                      <tr key={h.code} className="clickable" onClick={() => navigate('/thresholds#def-' + h.code)}>
                        <td className="mono">{h.code}</td>
                        <td>{h.name}</td>
                        <td className="num">{h.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card-head-static"><strong>最近 10 份</strong><span className="muted small">点击看报告</span></div>
        <div className="card-body">
          <table className="mini">
            <thead><tr><th>任务</th><th>状态</th><th>银行</th><th>笔数</th><th>评分</th><th>结论</th></tr></thead>
            <tbody>
              {data.recent.map(r => (
                <tr key={r.task_id} className="clickable" onClick={() => navigate('/report/' + r.task_id)}>
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
        </div>
      </section>

      <p className="muted small">
        口径：任务数为未删除任务；笔数取自解析出的流水；评分与结论取自每份任务的最新报告版本；
        覆盖率告警来自受理时的解析自检。
      </p>
    </div>
  );
}
