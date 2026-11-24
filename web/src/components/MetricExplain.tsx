import { useMemo } from 'react';
import type { MetricDef, TxnRow } from '../api/banker';

interface MetricExplainProps {
  metric: { code: string; name: string; value: string | null; unit: string; note: string; caliber_version?: number };
  def?: MetricDef;
  trend?: { month: string; income: string; expense: string }[];
  txns?: TxnRow[] | null;
  thresholdHint?: string | null;
}

function fmt(n: number) {
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

/** 指标点开后的可解释面板：展示口径公式、所需输入、口径版本、参考阈值与可视化序列。 */
export function MetricExplain({ metric, def, trend, txns, thresholdHint }: MetricExplainProps) {
  const vizType = def?.viz || 'scalar';

  const chartContent = useMemo(() => {
    if ((vizType === 'monthly_bars' || vizType === 'in_out_bars') && trend && trend.length > 0) {
      const W = 560;
      const H = 130;
      const PAD = { l: 12, r: 12, t: 14, b: 22 };
      const iw = W - PAD.l - PAD.r;
      const ih = H - PAD.t - PAD.b;
      const vals = trend.map((t) => [Number(t.income || 0), Number(t.expense || 0)]);
      const max = Math.max(1, ...vals.flat());
      const slot = iw / trend.length;
      const bw = Math.max(4, Math.min(18, slot * 0.35));
      return (
        <svg viewBox={`0 0 ${W} ${H}`} className="chart" style={{ maxWidth: 560, height: 'auto' }}>
          {trend.map((t, i) => {
            const x = PAD.l + i * slot;
            const inH = (vals[i][0] / max) * ih;
            const outH = (vals[i][1] / max) * ih;
            return (
              <g key={t.month}>
                <rect x={x + slot * 0.12} y={PAD.t + ih - inH} width={bw} height={inH} fill="#2563eb" rx="2" />
                <rect x={x + slot * 0.12 + bw + 2} y={PAD.t + ih - outH} width={bw} height={outH} fill="#f59e0b" rx="2" />
                <text x={x + slot / 2} y={H - 5} textAnchor="middle" fontSize="9" fill="#64748b">
                  {t.month.slice(2)}
                </text>
              </g>
            );
          })}
        </svg>
      );
    }

    if (vizType === 'balance_line' && txns && txns.length > 1) {
      const pts = txns
        .map((t) => ({ d: t.txn_date || '', b: t.balance !== null ? Number(t.balance) : Number.NaN }))
        .filter((p) => !Number.isNaN(p.b));
      if (pts.length > 1) {
        const W = 560;
        const H = 120;
        const PAD = { l: 12, r: 12, t: 10, b: 18 };
        const iw = W - PAD.l - PAD.r;
        const ih = H - PAD.t - PAD.b;
        const min = Math.min(...pts.map((p) => p.b));
        const max = Math.max(...pts.map((p) => p.b));
        const x = (i: number) => PAD.l + (i / (pts.length - 1)) * iw;
        const y = (v: number) => PAD.t + ih - ((v - min) / (max - min || 1)) * ih;
        const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.b).toFixed(1)}`).join(' ');
        return (
          <svg viewBox={`0 0 ${W} ${H}`} className="chart" style={{ maxWidth: 560, height: 'auto' }}>
            <path d={d} fill="none" stroke="#2563eb" strokeWidth="1.6" />
            <text x={PAD.l} y={H - 4} fontSize="9" fill="#64748b">最低 ¥{fmt(min)}</text>
            <text x={W - PAD.r} y={H - 4} textAnchor="end" fontSize="9" fill="#64748b">最高 ¥{fmt(max)}</text>
          </svg>
        );
      }
    }

    if (vizType === 'counterparty_bars' && txns && txns.length > 0) {
      const map = new Map<string, number>();
      for (const t of txns) {
        const cp = (t.counterparty_name || '').trim() || '未记户名';
        const amt = Math.abs(Number(t.amount || 0));
        if (!Number.isNaN(amt)) map.set(cp, (map.get(cp) ?? 0) + amt);
      }
      const top = [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
      const max = Math.max(1, ...top.map((i) => i[1]));
      if (top.length > 0) {
        return (
          <div className="catbars" style={{ maxWidth: 520 }}>
            {top.map(([name, val]) => (
              <div key={name} className="catbar">
                <span className="cat-name">{name}</span>
                <span className="cat-track">
                  <span className="cat-fill" style={{ width: `${(val / max) * 100}%` }} />
                </span>
                <span className="cat-val">¥{fmt(val)}</span>
              </div>
            ))}
          </div>
        );
      }
    }

    return null;
  }, [vizType, trend, txns]);

  return (
    <div className="metric-explain">
      <div className="me-grid">
        <div>
          <span className="me-k">指标分组</span>
          <span className="me-v">{def?.group || '标准指标'}</span>
        </div>
        <div>
          <span className="me-k">计算公式</span>
          <span className="me-v"><code>{def?.formula || '—'}</code></span>
        </div>
        <div>
          <span className="me-k">所需输入</span>
          <span className="me-v">{def?.inputs || '流水日期 / 金额 / 方向'}</span>
        </div>
        <div>
          <span className="me-k">本次测算</span>
          <span className="me-v">
            {metric.value === null ? '不可算（缺必需列或本期无此类交易）' : `${metric.value} ${metric.unit}`}
          </span>
        </div>
        <div>
          <span className="me-k">口径说明</span>
          <span className="me-v">{metric.note || '—'}</span>
        </div>
        <div>
          <span className="me-k">口径与阈值</span>
          <span className="me-v">
            口径 v{metric.caliber_version ?? '1'}
            {thresholdHint ? ` · 阈值参考：${thresholdHint}` : ''}
          </span>
        </div>
      </div>
      {chartContent ? (
        <div className="me-viz">
          <div className="small muted" style={{ marginBottom: 4 }}>关联分布可视化（来自当前任务流水）：</div>
          {chartContent}
        </div>
      ) : null}
    </div>
  );
}
