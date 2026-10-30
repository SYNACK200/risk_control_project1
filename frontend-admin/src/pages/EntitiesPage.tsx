import { useEffect, useState } from 'react';
import { getEntities, getMergeMethods, mergeSubject, type EntitiesPayload, type SubjectMergeMethod, type SubjectMergeResult } from '../lib/api';

const RISK_TEXT: Record<string, string> = { high: '高', medium: '中', low: '低', none: '未见' };

export function EntitiesPage() {
  const [data, setData] = useState<EntitiesPayload | null>(null);
  const [methods, setMethods] = useState<SubjectMergeMethod[]>([]);
  const [overlaps, setOverlaps] = useState<{ id: string; label: string; detail: string }[]>([]);
  const [subject, setSubject] = useState<string | null>(null);
  const [method, setMethod] = useState('net_internal');
  const [overlap, setOverlap] = useState('max');
  const [result, setResult] = useState<SubjectMergeResult | null>(null);
  const [showWhy, setShowWhy] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getEntities()
      .then(d => {
        setData(d);
        setError('');
        const first = d.subjects.find(s => Object.keys(s.accounts).length > 1) ?? d.subjects[0];
        if (first?.holder_masked) setSubject(first.holder_masked);
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)));
    getMergeMethods()
      .then(d => { setMethods(d.methods); setOverlaps(d.overlap_modes); })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!subject) return;
    let alive = true;
    setLoading(true);
    mergeSubject(subject, method, overlap)
      .then(r => { if (alive) { setResult(r); setError(''); } })
      .catch(e => { if (alive) { setResult(null); setError(e instanceof Error ? e.message : String(e)); } })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [subject, method, overlap]);

  const current = methods.find(m => m.id === method);
  const conflictCount = data?.summary.conflicts ?? 0;

  return (
    <div className="result-wrap">
      <div className="result">
        <div className="result-head">
          <h2>客户与账户</h2>
          <span className="muted">账户 {data?.summary.accounts ?? 0} 个 · 户名 {data?.summary.subjects ?? 0} 个 · 多账户客户 {data?.summary.multi_account_subjects ?? 0} 个</span>
        </div>

        {conflictCount > 0 && (
          <div className="conflict-box">
            <div className="conflict-head">发现 {conflictCount} 个账户对应多个户名，需要核查</div>
            {(data?.conflicts ?? []).map(c => (
              <div key={c.account_key} className="conflict-row">
                <span className="tag fail">高风险</span>
                <strong>{c.bank_name ?? '银行未识别'} {c.account_masked ?? '账号未识别'}</strong>
                <span className="muted">户名：{c.holders.join(' / ')} · 涉及任务 {c.tasks.join('、')}</span>
                <span className="conflict-msg">{c.message}</span>
              </div>
            ))}
          </div>
        )}

        <h3>选择客户</h3>
        <p className="muted">同一户名下的多个账户会合并成一份风险画像；合并方式不同，结果含义不同。</p>
        <div className="filter-row">
          {(data?.subjects ?? []).map(s => {
            const accounts = Object.keys(s.accounts).length;
            const disabled = !s.holder_masked;
            return (
              <button
                key={s.key}
                type="button"
                disabled={disabled}
                className={'filter-chip' + (subject === s.holder_masked ? ' active' : '')}
                onClick={() => s.holder_masked && setSubject(s.holder_masked)}
              >
                {s.holder_masked ?? '未识别户名'} · {accounts} 账户 / {s.tasks.length} 份
              </button>
            );
          })}
        </div>

        <h3>合并方式</h3>
        <div className="filter-row">
          {methods.map(m => (
            <button key={m.id} type="button" className={'filter-chip' + (method === m.id ? ' active' : '')} onClick={() => setMethod(m.id)}>
              {m.label}
            </button>
          ))}
          {overlaps.length > 1 && (<>
            <span className="filter-label" style={{ marginLeft: 14 }}>重叠月份</span>
            <select value={overlap} onChange={e => setOverlap(e.target.value)}>
              {overlaps.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
          </>)}
          <button className="link-btn" type="button" onClick={() => setShowWhy(v => !v)}>{showWhy ? '收起说明' : '这个方式怎么算？'}</button>
        </div>
        {current && <p className="muted">当前：<strong>{current.label}</strong> —— {current.short}</p>}
        {showWhy && current && (
          <div className="why-box">
            <div><span className="me-k">做法</span><span className="me-v">{current.detail}</span></div>
            <div><span className="me-k">公式</span><code className="me-formula">{current.formula}</code></div>
            <div><span className="me-k">假设</span><span className="me-v">{current.assumption}</span></div>
            <div><span className="me-k">比率类</span><span className="me-v">月均、DTI、流入流出比不直接相加，按合并后的分子分母重算。</span></div>
            <div><span className="me-k">余额类</span><span className="me-v">余额不跨账户相加：同一时点同一笔钱只存在一个账户里。</span></div>
          </div>
        )}

        {error && <div className="notice error">{error}</div>}
        {loading && <p className="muted">正在合并…</p>}

        {result && !loading && (
          <section style={{ marginTop: 16 }}>
            <div className="merge-head">
              <span className={'tag risk-' + result.risk.level}>信用风险 {RISK_TEXT[result.risk.level] ?? result.risk.level}</span>
              <span className="muted">命中 {result.risk.hits} 项 · 覆盖 {result.coverage.months} 个月（{result.coverage.from} ~ {result.coverage.to}）· 重叠 {result.coverage.overlap_months.length} 个月</span>
            </div>

            <table className="mini">
              <thead><tr><th>指标</th><th>合并值</th><th>单位</th><th>怎么来的</th></tr></thead>
              <tbody>
                {result.metrics.map(m => (
                  <tr key={m.code}>
                    <td>{m.name} <span className="muted small">{m.code}</span></td>
                    <td className="num">{m.value === null ? '不可算' : m.value.toLocaleString()}</td>
                    <td>{m.unit}</td>
                    <td className="muted">{m.how}{m.note ? ' · ' + m.note : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {result.warnings.length > 0 && (
              <div className="why-box">
                <span className="me-k">需要留意</span>
                <ul className="muted">{result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
              </div>
            )}

            <h3>参与合并的账户（{result.accounts.length}）</h3>
            <table className="mini">
              <thead><tr><th>任务</th><th>银行</th><th>账号</th><th>有数据月数</th><th>笔数</th><th>期末余额</th><th>风险命中</th></tr></thead>
              <tbody>
                {result.accounts.map(a => (
                  <tr key={a.task_id}>
                    <td className="mono">{a.task_id}</td>
                    <td>{a.bank_name ?? '—'}</td>
                    <td className="mono">{a.account_masked ?? '—'}</td>
                    <td className="num">{a.months}</td>
                    <td className="num">{a.txn_count}</td>
                    <td className="num">{a.balance_end ?? '—'}</td>
                    <td className="num">{a.risk_hits}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h3>不参与合并的指标</h3>
            <ul className="muted">
              {result.unsupported.map(u => <li key={u.code}>{u.code} {u.name}：{u.reason}</li>)}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}

