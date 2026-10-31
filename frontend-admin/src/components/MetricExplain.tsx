import { useMemo } from 'react';
import type { MetricDef, ReportPayload, TxnRow } from '../lib/api';

interface Props {
  metric: ReportPayload['metrics'][number];
  def?: MetricDef;
  trend: { month: string; income: string; expense: string }[];
  txns: TxnRow[];
  metricSetVersion?: number;
}

function num(v?: string | number | null): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

interface SeriesProps {
  labels: string[];
  values: number[];
  unit: string;
  color?: string;
  refValue?: number | null;
  refLabel?: string;
}

function BarSeries({ labels, values, unit, color = '#2f6fed', refValue, refLabel }: SeriesProps) {
  const w = 560, h = 170, padL = 54, padB = 30, padT = 12;
  const max = Math.max(1, ...values.map(v => Math.abs(v)));
  const bw = values.length > 0 ? (w - padL - 10) / values.length : 10;
  const zeroY = padT + (h - padT - padB) / 2;
  const scale = (v: number) => (v / max) * ((h - padT - padB) / 2);
  const refY = refValue !== null && refValue !== undefined ? zeroY - scale(refValue) : null;
  return (
    <svg viewBox={'0 0 ' + w + ' ' + h} className="metric-svg" role="img">
      <line x1={padL} y1={zeroY} x2={w - 8} y2={zeroY} stroke="#c9d3e3" />
      {refY !== null && (
        <>
          <line x1={padL} y1={refY} x2={w - 8} y2={refY} stroke="#e08a1e" strokeDasharray="5 4" />
          <text x={w - 8} y={refY - 4} textAnchor="end" fontSize="10" fill="#b06f11">{refLabel}</text>
        </>
      )}
      {values.map((v, i) => {
        const barH = Math.max(1, scale(Math.abs(v)));
        const x = padL + i * bw + bw * 0.18;
        const y = v >= 0 ? zeroY - barH : zeroY;
        return (
          <g key={i}>
            <rect x={x} y={y} width={bw * 0.64} height={barH} fill={v >= 0 ? color : '#d9534f'} rx="2" />
            <text x={x + bw * 0.32} y={h - 10} textAnchor="middle" fontSize="9" fill="#68758a">{labels[i]}</text>
          </g>
        );
      })}
      <text x={6} y={padT + 6} fontSize="10" fill="#68758a">{unit}</text>
    </svg>
  );
}

function LineSeries({ labels, values, unit }: SeriesProps) {
  const w = 560, h = 170, padL = 54, padB = 30, padT = 12;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const xAt = (i: number) => padL + (i * (w - padL - 12)) / Math.max(1, values.length - 1);
  const yAt = (v: number) => padT + (1 - (v - min) / span) * (h - padT - padB);
  const points = values.map((v, i) => xAt(i) + ',' + yAt(v)).join(' ');
  return (
    <svg viewBox={'0 0 ' + w + ' ' + h} className="metric-svg" role="img">
      <polyline points={points} fill="none" stroke="#2f6fed" strokeWidth="2" />
      <text x={6} y={padT + 6} fontSize="10" fill="#68758a">{unit}（最高 {max.toFixed(2)} / 最低 {min.toFixed(2)}）</text>
      <text x={padL} y={h - 10} fontSize="9" fill="#68758a">{labels[0] ?? ''}</text>
      <text x={w - 12} y={h - 10} fontSize="9" fill="#68758a" textAnchor="end">{labels[labels.length - 1] ?? ''}</text>
    </svg>
  );
}

export function MetricExplain({ metric, def, trend, txns, metricSetVersion }: Props) {
  const viz = def?.viz ?? 'none';
  const value = num(metric.value);

  const incomeSeries = useMemo(() => ({ labels: trend.map(t => t.month.slice(5)), values: trend.map(t => num(t.income) ?? 0) }), [trend]);
  const expenseSeries = useMemo(() => ({ labels: trend.map(t => t.month.slice(5)), values: trend.map(t => num(t.expense) ?? 0) }), [trend]);
  const netSeries = useMemo(() => ({ labels: trend.map(t => t.month.slice(5)), values: trend.map(t => (num(t.income) ?? 0) - (num(t.expense) ?? 0)) }), [trend]);
  const balanceSeries = useMemo(() => {
    const rows = txns.filter(t => num(t.balance) !== null).slice(0, 120);
    return { labels: rows.map(t => (t.txn_date ?? '').slice(5)), values: rows.map(t => num(t.balance) as number) };
  }, [txns]);
  const countSeries = useMemo(() => {
    const buckets = new Map<string, number>();
    for (const t of txns) {
      const m = (t.txn_date ?? '').slice(0, 7);
      if (m) buckets.set(m, (buckets.get(m) ?? 0) + 1);
    }
    const keys = Array.from(buckets.keys()).sort();
    return { labels: keys.map(k => k.slice(5)), values: keys.map(k => buckets.get(k) as number) };
  }, [txns]);
  const topAmounts = useMemo(() => {
    const rows = txns
      .map(t => ({ date: (t.txn_date ?? '').slice(5), amount: Math.abs(num(t.amount) ?? 0) }))
      .filter(r => r.amount > 0)
      .sort((a, b) => b.amount - a.amount)
      .slice(0, 8);
    return { labels: rows.map(r => r.date), values: rows.map(r => r.amount) };
  }, [txns]);
  const amountHist = useMemo(() => {
    const edges = [0, 500, 2000, 5000, 10000, Infinity];
    const names = ['<500', '500-2k', '2k-5k', '5k-1w', '>1w'];
    const counts = new Array(names.length).fill(0);
    for (const t of txns) {
      const a = Math.abs(num(t.amount) ?? 0);
      if (a <= 0) continue;
      for (let i = 0; i < names.length; i += 1) {
        if (a >= edges[i] && a < edges[i + 1]) { counts[i] += 1; break; }
      }
    }
    return { labels: names, values: counts };
  }, [txns]);

  const counterpartySeries = useMemo(() => {
    const sums = new Map<string, number>();
    for (const t of txns) {
      const key = t.counterparty_name?.trim();
      if (!key) continue;
      sums.set(key, (sums.get(key) ?? 0) + (num(t.amount) ?? 0));
    }
    const top = Array.from(sums.entries()).sort((a, b) => b[1] - a[1]).slice(0, 6);
    return { labels: top.map(x => x[0].slice(0, 6)), values: top.map(x => x[1]) };
  }, [txns]);

  return (
    <div className="metric-explain">
      <div className="me-grid">
        <div><span className="me-k">计算规则</span><code className="me-formula">{def?.formula ?? '（定义未加载）'}</code></div>
        <div><span className="me-k">输入</span><span className="me-v">{def?.inputs || '—'}</span></div>
        <div><span className="me-k">口径版本</span><span className="me-v">单项口径 v{metric.caliber_version ?? '—'} · 指标集 v{metricSetVersion ?? '—'}</span></div>
        <div><span className="me-k">当前值</span><span className="me-v mono">{metric.value ?? '不可算'}{metric.unit ? ' ' + metric.unit : ''}</span></div>
      </div>
      <p className="me-note">{metric.note || '无附加说明'}</p>
      {value === null && <p className="me-warn">该指标本份材料不可算：上图/下表只展示能拿到的原始数据。</p>}

      {viz === 'none' && <p className="muted">该指标没有直观图形，按上方公式与输入计算。</p>}
      {viz === 'monthly_income' && (<><h4>月度入账（用于 A 组计算）</h4><BarSeries labels={incomeSeries.labels} values={incomeSeries.values} unit="元/月" refValue={value} refLabel="本指标值" /></>)}
      {viz === 'monthly_expense' && (<><h4>月度出账（用于 B 组计算）</h4><BarSeries labels={expenseSeries.labels} values={expenseSeries.values} unit="元/月" /></>)}
      {viz === 'monthly_net' && (<><h4>月度净流入</h4><BarSeries labels={netSeries.labels} values={netSeries.values} unit="元/月" /></>)}
      {viz === 'balance' && (<><h4>余额走势（明细前 120 笔）</h4><LineSeries labels={balanceSeries.labels} values={balanceSeries.values} unit="元" /></>)}
      {viz === 'monthly_count' && (<><h4>月度交易笔数</h4><BarSeries labels={countSeries.labels} values={countSeries.values} unit="笔/月" /></>)}
      {viz === 'top_amounts' && (<><h4>单笔金额前 8 笔</h4><BarSeries labels={topAmounts.labels} values={topAmounts.values} unit="元/笔" /></>)}
      {viz === 'amount_hist' && (<><h4>单笔金额分布（笔数）</h4><BarSeries labels={amountHist.labels} values={amountHist.values} unit="笔" /></>)}
      {viz === 'counterparty_bars' && (counterpartySeries.values.length > 0
        ? (<><h4>对手方金额前 6</h4><BarSeries labels={counterpartySeries.labels} values={counterpartySeries.values} unit="元" /></>)
        : (<p className="muted">本份材料没有对手方字段，无法画该图。</p>))}
    </div>
  );
}
