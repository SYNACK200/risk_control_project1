/** 报告里的小图表：只用 SVG，不引图表库（几百 KB 不值当，图形只有三四种）。 */
import { useMemo } from 'react';
import type { TxnRow } from '../api/banker';

export function Bar({
  value,
  max = 100,
  tone = 'brand',
}: {
  value: number;
  max?: number;
  tone?: 'brand' | 'warn' | 'bad' | 'muted';
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const color = { brand: '#2563eb', warn: '#d97706', bad: '#b91c1c', muted: '#94a3b8' }[tone];
  return (
    <span className="bar-track" title={String(value)}>
      <span className="bar-fill" style={{ width: pct + '%', background: color }} />
    </span>
  );
}

/** 业务域五维雷达图。 */
export function DomainRadar({ domains }: { domains: { key: string; name: string; score: number }[] }) {
  if (!domains || domains.length < 3) return null;
  const cx = 140;
  const cy = 125;
  const rMax = 78;
  const n = domains.length;
  const pt = (idx: number, ratio: number) => {
    const angle = -Math.PI / 2 + (idx * 2 * Math.PI) / n;
    return [cx + Math.cos(angle) * rMax * ratio, cy + Math.sin(angle) * rMax * ratio];
  };
  const dataPoints = domains.map((d, i) => pt(i, Math.max(0.05, Math.min(1, (d.score ?? 0) / 100))));

  return (
    <svg className="radar-chart" viewBox="0 0 280 250" role="img" aria-label="业务域得分雷达图">
      {[0.25, 0.5, 0.75, 1].map((lv) => (
        <polygon
          key={lv}
          points={domains.map((_, i) => pt(i, lv).join(',')).join(' ')}
          fill="none"
          stroke="#e2e8f0"
          strokeWidth="1"
        />
      ))}
      {domains.map((d, i) => {
        const [x, y] = pt(i, 1);
        const [lx, ly] = pt(i, 1.24);
        return (
          <g key={d.key}>
            <line x1={cx} y1={cy} x2={x} y2={y} stroke="#e2e8f0" strokeWidth="1" />
            <text x={lx} y={ly} textAnchor="middle" dominantBaseline="middle" fontSize="11" fill="#334155">
              {d.name}
            </text>
          </g>
        );
      })}
      <polygon
        points={dataPoints.map((p) => p.join(',')).join(' ')}
        fill="rgba(37, 99, 235, 0.16)"
        stroke="#2563eb"
        strokeWidth="2"
      />
      {dataPoints.map(([x, y], i) => (
        <circle key={domains[i].key} cx={x} cy={y} r="3.5" fill="#1d4ed8">
          <title>{`${domains[i].name}: ${domains[i].score}`}</title>
        </circle>
      ))}
    </svg>
  );
}

/** 月度收支：柱状（收入/支出）+ 净额折线。 */
export function MonthlyFlow({ series }: { series: { month: string; income: string; expense: string }[] }) {
  if (!series.length) return <p className="muted small">没有月度数据。</p>;
  const W = 720;
  const H = 200;
  const PAD = { l: 8, r: 8, t: 12, b: 26 };
  const width = W - PAD.l - PAD.r;
  const height = H - PAD.t - PAD.b;
  const income = series.map((item) => Number(item.income || 0));
  const expense = series.map((item) => Number(item.expense || 0));
  const max = Math.max(...income, ...expense, 1);
  const slot = width / series.length;
  const barW = Math.max(3, slot * 0.34);
  const net = income.map((value, index) => value - expense[index]);
  const netMax = Math.max(...net.map(Math.abs), 1);

  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="月度收支">
      {[0.25, 0.5, 0.75, 1].map((ratio) => (
        <line
          key={ratio}
          x1={PAD.l}
          x2={W - PAD.r}
          y1={PAD.t + height * (1 - ratio)}
          y2={PAD.t + height * (1 - ratio)}
          stroke="#e5eaf2"
          strokeWidth="1"
        />
      ))}
      {series.map((item, index) => {
        const x = PAD.l + index * slot;
        const inH = (income[index] / max) * height;
        const outH = (expense[index] / max) * height;
        return (
          <g key={item.month}>
            <rect x={x + slot * 0.12} y={PAD.t + height - inH} width={barW} height={inH} fill="#2563eb" rx="2" />
            <rect x={x + slot * 0.12 + barW + 2} y={PAD.t + height - outH} width={barW} height={outH} fill="#f59e0b" rx="2" />
            <text x={x + slot / 2} y={H - 8} textAnchor="middle" fontSize="10" fill="#94a3b8">
              {item.month.slice(2)}
            </text>
          </g>
        );
      })}
      <polyline
        fill="none"
        stroke="#0f172a"
        strokeWidth="1.4"
        strokeDasharray="4 3"
        points={net
          .map((value, index) => {
            const x = PAD.l + index * slot + slot / 2;
            const y = PAD.t + height / 2 - (value / netMax) * (height / 2 - 4);
            return x + ',' + y;
          })
          .join(' ')}
      />
      <text x={PAD.l} y={PAD.t + 10} fontSize="10" fill="#2563eb">收入</text>
      <text x={PAD.l + 30} y={PAD.t + 10} fontSize="10" fill="#f59e0b">支出</text>
      <text x={PAD.l + 60} y={PAD.t + 10} fontSize="10" fill="#0f172a">净额（虚线）</text>
    </svg>
  );
}

/** 金额分布：按数量级分桶，看钱集中在小额还是大额。 */
export function AmountHistogram({ amounts }: { amounts: number[] }) {
  const buckets = [
    { label: '<1千', min: 0, max: 1000 },
    { label: '1千–1万', min: 1000, max: 10000 },
    { label: '1万–5万', min: 10000, max: 50000 },
    { label: '5万–20万', min: 50000, max: 200000 },
    { label: '≥20万', min: 200000, max: Infinity },
  ];
  const counts = buckets.map((bucket) => amounts.filter((v) => Math.abs(v) >= bucket.min && Math.abs(v) < bucket.max).length);
  const max = Math.max(...counts, 1);
  const total = amounts.length || 1;

  return (
    <table className="grid compact chart-table">
      <thead><tr><th>金额区间</th><th>笔数</th><th>占比</th></tr></thead>
      <tbody>
        {buckets.map((bucket, index) => (
          <tr key={bucket.label}>
            <td>{bucket.label}</td>
            <td>{counts[index]}</td>
            <td>
              <span className="bar-inline">
                <Bar value={counts[index]} max={max} />
                <span className="muted small">{Math.round((counts[index] / total) * 100)}%</span>
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const fmtMoney = (n: number) => n.toLocaleString('zh-CN', { maximumFractionDigits: 2 });

const INSIGHT_CATS: [RegExp, string][] = [
  [/工资|代发|薪/, '工资代发'],
  [/利息|结息/, '利息'],
  [/汇入|转入|入账/, '转入/汇入'],
  [/汇出|转出|汇款/, '转出/汇款'],
  [/消费|快捷|支付|商户/, '消费支付'],
  [/还款|贷款/, '贷款还款'],
  [/基金|理财|证券/, '投资理财'],
  [/退|冲正/, '退款/冲正'],
];

function insightCatOf(summary: string | null): string {
  if (!summary) return '其他';
  for (const [re, label] of INSIGHT_CATS) if (re.test(summary)) return label;
  return '其他';
}

/** 资金全景与逐笔余额走势/摘要结构图表。 */
export function InsightSection({ txns }: { txns: TxnRow[] }) {
  const insight = useMemo(() => {
    const monthsMap = new Map<string, { income: number; expense: number }>();
    const catMap = new Map<string, number>();
    const balancePoints: { date: string; balance: number }[] = [];
    let income = 0;
    let expense = 0;
    let maxIn: { date: string; amount: number; summary: string | null } | undefined;
    let maxOut: { date: string; amount: number; summary: string | null } | undefined;
    let minBalance: { date: string; balance: number } | undefined;

    for (const t of txns) {
      const amt = t.amount === null ? Number.NaN : Number(t.amount);
      const dir = t.direction === 'in' ? 'in' : t.direction === 'out' ? 'out' : null;
      if (!Number.isNaN(amt) && dir) {
        const m = t.txn_date ? t.txn_date.slice(0, 7) : '未知';
        const cell = monthsMap.get(m) ?? { income: 0, expense: 0 };
        if (dir === 'in') {
          cell.income += amt;
          income += amt;
          if (amt > 0 && (!maxIn || amt > maxIn.amount)) maxIn = { date: t.txn_date ?? '', amount: amt, summary: t.summary };
        } else {
          cell.expense += amt;
          expense += amt;
          if (!maxOut || amt > maxOut.amount) maxOut = { date: t.txn_date ?? '', amount: amt, summary: t.summary };
        }
        monthsMap.set(m, cell);
        const cat = insightCatOf(t.summary);
        catMap.set(cat, (catMap.get(cat) ?? 0) + Math.abs(amt));
      }
      const bal = t.balance === null ? Number.NaN : Number(t.balance);
      if (!Number.isNaN(bal) && t.txn_date) {
        balancePoints.push({ date: t.txn_date, balance: bal });
        if (!minBalance || bal < minBalance.balance) minBalance = { date: t.txn_date, balance: bal };
      }
    }

    return {
      months: [...monthsMap.entries()]
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([month, v]) => ({ month, income: String(v.income), expense: String(v.expense) })),
      balancePoints,
      categories: [...catMap.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6)
        .map(([name, amount]) => ({ name, amount })),
      count: txns.length,
      income,
      expense,
      net: income - expense,
      maxIn,
      maxOut,
      minBalance,
    };
  }, [txns]);

  if (txns.length === 0) return null;

  const pts = insight.balancePoints;
  const W = 720;
  const H = 200;
  const PAD = { l: 56, r: 16, t: 16, b: 28 };
  const iw = W - PAD.l - PAD.r;
  const ih = H - PAD.t - PAD.b;
  const maxBal = Math.max(1, ...pts.map((p) => p.balance));
  const minBal = Math.min(0, ...pts.map((p) => p.balance));
  const bx = (i: number) => PAD.l + (pts.length <= 1 ? iw / 2 : (i / (pts.length - 1)) * iw);
  const by = (v: number) => PAD.t + ih - ((v - minBal) / (maxBal - minBal || 1)) * ih;
  const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${bx(i).toFixed(1)},${by(p.balance).toFixed(1)}`).join(' ');
  const totalFlow = insight.income + insight.expense || 1;
  const maxCat = Math.max(1, ...insight.categories.map((c) => c.amount));

  return (
    <section style={{ marginTop: 12 }}>
      <h2>资金全景（明细全量统计）</h2>
      <div className="tiles">
        <div className="tile"><div className="tile-label">交易笔数</div><div className="tile-value">{insight.count} 笔</div></div>
        <div className="tile good"><div className="tile-label">期间收入</div><div className="tile-value">¥{fmtMoney(insight.income)}</div></div>
        <div className="tile bad"><div className="tile-label">期间支出</div><div className="tile-value">¥{fmtMoney(insight.expense)}</div></div>
        <div className={'tile ' + (insight.net >= 0 ? 'good' : 'bad')}>
          <div className="tile-label">净流入</div>
          <div className="tile-value">¥{fmtMoney(insight.net)}</div>
        </div>
        <div className="tile warn">
          <div className="tile-label">最低余额</div>
          <div className="tile-value">{insight.minBalance ? `¥${fmtMoney(insight.minBalance.balance)}` : '—'}</div>
        </div>
      </div>

      <div className="chart-grid">
        <div className="chart-card">
          <h4>逐笔余额走势</h4>
          {pts.length ? (
            <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="余额走势">
              {[0, 0.5, 1].map((k) => (
                <g key={k}>
                  <line x1={PAD.l} x2={W - PAD.r} y1={PAD.t + ih * k} y2={PAD.t + ih * k} stroke="#e6e9ef" />
                  <text x={PAD.l - 8} y={PAD.t + ih * k + 4} textAnchor="end" fontSize="10" fill="#64748b">
                    {fmtMoney(Math.round(maxBal - (maxBal - minBal) * k))}
                  </text>
                </g>
              ))}
              <path d={path} fill="none" stroke="#2563eb" strokeWidth="1.6" />
            </svg>
          ) : (
            <p className="muted small">无可用余额点</p>
          )}
        </div>
        <div className="chart-card">
          <h4>摘要结构（按金额） & 重点事项</h4>
          <div className="catbars">
            {insight.categories.map((c) => (
              <div key={c.name} className="catbar">
                <span className="cat-name">{c.name}</span>
                <span className="cat-track">
                  <span className="cat-fill" style={{ width: `${(c.amount / maxCat) * 100}%` }} />
                </span>
                <span className="cat-val">¥{fmtMoney(c.amount)} ({((c.amount / totalFlow) * 100).toFixed(1)}%)</span>
              </div>
            ))}
          </div>
          <ul className="plain small muted" style={{ marginTop: 8 }}>
            {insight.maxOut ? <li>最大单笔支出：{insight.maxOut.date} ¥{fmtMoney(insight.maxOut.amount)}（{insight.maxOut.summary ?? '—'}）</li> : null}
            {insight.maxIn ? <li>最大单笔收入：{insight.maxIn.date} ¥{fmtMoney(insight.maxIn.amount)}（{insight.maxIn.summary ?? '—'}）</li> : null}
            {insight.minBalance ? <li>余额最低点：{insight.minBalance.date} ¥{fmtMoney(insight.minBalance.balance)}</li> : null}
          </ul>
        </div>
      </div>
    </section>
  );
}

