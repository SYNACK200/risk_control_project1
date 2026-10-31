import { useEffect, useState } from 'react';
import { getMergeModes, listTasks, mergeTasks, type FlowMergeMode, type FlowMergeResult, type TaskSummary } from '../lib/api';

const SIMPLE: { key: string; label: string; hint: string }[] = [
  { key: 'net_internal', label: '合并（推荐）', hint: '去掉互转与重复，最接近真实规模' },
  { key: 'worst_case', label: '保守估计', hint: '按最差账户评价，授信偏严' },
  { key: 'separate', label: '分开看', hint: '不合并，逐账户对比' },
];

function money(v: string | null | undefined) {
  if (!v) return '—';
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) : v;
}

export function MergePage() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [picked, setPicked] = useState<number[]>([]);
  const [mode, setMode] = useState('net_internal');
  const [modes, setModes] = useState<FlowMergeMode[]>([]);
  const [advanced, setAdvanced] = useState(false);
  const [result, setResult] = useState<FlowMergeResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listTasks({ limit: 200 }).then(d => setTasks(d.items)).catch(e => setError(String(e)));
    getMergeModes().then(d => setModes(d.items)).catch(() => setModes([]));
  }, []);

  const current = modes.find(m => m.key === mode);

  function toggle(id: number) {
    setPicked(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }

  async function run() {
    if (picked.length < 2) { setError('至少选两个账户'); return; }
    setBusy(true); setError(''); setResult(null);
    try {
      setResult(await mergeTasks(picked, mode));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const metric = (code: string) => result?.metrics.find(m => m.code === code)?.value;

  return (
    <div className="result-wrap">
      <div className="result">
        <div className="result-head"><h2>账户合并</h2><span className="muted">把同一借款人的多个账户合成一个视图</span></div>
        {error && <div className="notice error">{error}</div>}

        <h3>1. 选账户（已选 {picked.length}）</h3>
        <table className="mini list-table">
          <thead><tr><th></th><th>业务号</th><th>银行</th><th>账期</th><th>笔数</th><th>期间收入</th><th>流水合格性</th></tr></thead>
          <tbody>
            {tasks.map(t => (
              <tr key={t.id} className="list-row" onClick={() => toggle(t.id)}>
                <td><input type="checkbox" checked={picked.includes(t.id)} readOnly /></td>
                <td className="mono">{t.biz_no}</td>
                <td>{t.bank_name ?? '未识别'}</td>
                <td className="muted">{t.period_start ?? '—'} ~ {t.period_end ?? '—'}</td>
                <td className="num">{t.parse.txn_count}</td>
                <td className="num">{money(t.income)}</td>
                <td><span className={'tag ' + t.authenticity.level}>{t.authenticity.label}</span></td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3>2. 选合并方式</h3>
        <div className="merge-modes">
          {SIMPLE.map(item => (
            <button
              key={item.key}
              type="button"
              className={'merge-mode' + (mode === item.key ? ' active' : '')}
              onClick={() => { if (item.key !== 'separate') setMode(item.key); }}
            >
              <strong>{item.label}</strong>
              <span>{item.hint}</span>
            </button>
          ))}
        </div>
        <p className="muted">
          高级方式：
          <button type="button" className="link-btn" onClick={() => setAdvanced(!advanced)}>{advanced ? '收起' : '展开 5 种'}</button>
        </p>
        {advanced && (
          <select className="filter-select" value={mode} onChange={e => setMode(e.target.value)}>
            {modes.map(m => <option key={m.key} value={m.key}>{m.label} —— {m.one_line}</option>)}
          </select>
        )}
        {current && (
          <div className="merge-explain">
            <div><span className="me-k">公式</span><code className="me-formula">{current.formula}</code></div>
            <div><span className="me-k">适用</span><span className="me-v">{current.when}</span></div>
            <div><span className="me-k">已知偏差</span><span className="me-v">{current.caveat}</span></div>
          </div>
        )}

        <button className="btn" type="button" disabled={busy || picked.length < 2} onClick={() => { void run(); }}>
          {busy ? '合并中…' : '开始合并'}
        </button>

        {result && (
          <section style={{ marginTop: 22 }}>
            <h3>合并结果：{result.label}</h3>
            <div className="stat-strip">
              <div><span>合并期间</span><strong>{result.period_start ?? '—'} ~ {result.period_end ?? '—'}</strong></div>
              <div><span>重叠天数</span><strong>{result.overlap_days} 天</strong></div>
              <div><span>笔数（原始→合并）</span><strong>{result.raw_txn_count} → {result.txn_count}</strong></div>
              <div><span>期间收入</span><strong>{money(metric('A01'))}</strong></div>
              <div><span>月均收入</span><strong>{money(metric('A02'))}</strong></div>
              <div><span>净流入</span><strong>{money(metric('C01'))}</strong></div>
            </div>

            <h3>各账户贡献</h3>
            <table className="mini">
              <thead><tr><th>账户</th><th>期间</th><th>笔数</th><th>流入</th><th>流出</th></tr></thead>
              <tbody>{result.accounts.map(a => (
                <tr key={a.account_id}>
                  <td className="mono">{a.account_id}</td>
                  <td className="muted">{a.period_start ?? '—'} ~ {a.period_end ?? '—'}</td>
                  <td className="num">{a.txn_count}</td>
                  <td className="num">{money(a.inflow)}</td>
                  <td className="num">{money(a.outflow)}</td>
                </tr>
              ))}</tbody>
            </table>

            {result.internal_transfers.length > 0 && (
              <>
                <h3>被抵消的内部转账（{result.internal_transfers.length} 对）</h3>
                <table className="mini">
                  <thead><tr><th>金额</th><th>转出账户</th><th>转入账户</th><th>转出日</th><th>转入日</th></tr></thead>
                  <tbody>{result.internal_transfers.map((p, i) => (
                    <tr key={i}><td className="num">{money(p.amount)}</td><td className="mono">{p.from}</td><td className="mono">{p.to}</td><td>{p.out_date}</td><td>{p.in_date}</td></tr>
                  ))}</tbody>
                </table>
              </>
            )}

            {result.notes.length > 0 && <ul className="muted">{result.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}

            <h3>合并后的关键指标</h3>
            <table className="mini">
              <thead><tr><th>编码</th><th>指标</th><th>值</th><th>怎么来的</th></tr></thead>
              <tbody>{result.metrics.filter(m => m.value !== null).slice(0, 40).map(m => (
                <tr key={m.code}><td className="mono">{m.code}</td><td>{m.name}</td><td className="num">{m.value}</td><td className="muted">{m.basis}</td></tr>
              ))}</tbody>
            </table>
          </section>
        )}
      </div>
    </div>
  );
}
