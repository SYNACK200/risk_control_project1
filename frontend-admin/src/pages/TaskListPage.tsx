import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { listTasks, type TaskFilters, type TaskSummary, type TaskSummaryList } from '../lib/api';

const AUTH_TEXT: Record<string, string> = { pass: '合格', partial: '部分合格', fail: '不合格', unknown: '无法判定' };
const RISK_TEXT: Record<string, string> = { high: '高', medium: '中', low: '低', none: '未见' };
const PARSE_TEXT: Record<string, string> = { ok: '完整', partial: '不完整', failed: '失败' };

function Chip({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button type="button" className={'filter-chip' + (active ? ' active' : '')} onClick={onClick}>
      {children}
    </button>
  );
}

export function TaskListPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<TaskSummaryList | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState<TaskFilters>({});
  const [q, setQ] = useState('');

  useEffect(() => {
    let alive = true;
    setLoading(true);
    listTasks({ ...filters, q: q || undefined })
      .then(d => { if (alive) { setData(d); setError(''); } })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [filters, q]);

  function toggle(key: 'authenticity' | 'risk' | 'parse' | 'bank', value: string) {
    setFilters(prev => (prev[key] === value ? { ...prev, [key]: undefined } : { ...prev, [key]: value }));
  }

  const items: TaskSummary[] = data?.items ?? [];
  const facets = data?.facets;

  return (
    <div className="result-wrap">
      <div className="result">
        <div className="result-head">
          <h2>解析结果</h2>
          <span className="muted">{loading ? '加载中…' : '共 ' + (data?.total ?? 0) + ' 条'}</span>
        </div>

        <div className="filter-panel">
          <div className="filter-row">
            <span className="filter-label">流水合格性</span>
            <Chip active={!filters.authenticity} onClick={() => setFilters((p: TaskFilters) => ({ ...p, authenticity: undefined }))}>全部</Chip>
            {(['pass', 'partial', 'fail', 'unknown'] as const).map(level => (
              <Chip key={level} active={filters.authenticity === level} onClick={() => toggle('authenticity', level)}>
                {AUTH_TEXT[level]} {Number(facets?.authenticity?.[level] ?? 0)}
              </Chip>
            ))}
          </div>
          <div className="filter-row">
            <span className="filter-label">信用风险</span>
            <Chip active={!filters.risk} onClick={() => setFilters((p: TaskFilters) => ({ ...p, risk: undefined }))}>全部</Chip>
            {(['high', 'medium', 'low', 'none'] as const).map(level => (
              <Chip key={level} active={filters.risk === level} onClick={() => toggle('risk', level)}>
                {RISK_TEXT[level]} {Number(facets?.risk?.[level] ?? 0)}
              </Chip>
            ))}
          </div>
          <div className="filter-row">
            <span className="filter-label">解析质量</span>
            <Chip active={!filters.parse} onClick={() => setFilters((p: TaskFilters) => ({ ...p, parse: undefined }))}>全部</Chip>
            {(['ok', 'partial', 'failed'] as const).map(level => (
              <Chip key={level} active={filters.parse === level} onClick={() => toggle('parse', level)}>
                {PARSE_TEXT[level]} {Number(facets?.parse?.[level] ?? 0)}
              </Chip>
            ))}
          </div>
          <div className="filter-row">
            <span className="filter-label">银行</span>
            <Chip active={!filters.bank} onClick={() => setFilters((p: TaskFilters) => ({ ...p, bank: undefined }))}>全部</Chip>
            {Object.entries(facets?.bank ?? {}).map(([name, count]) => (
              <Chip key={name} active={filters.bank === name} onClick={() => toggle('bank', name)}>{name} {count}</Chip>
            ))}
          </div>
          <div className="filter-row">
            <span className="filter-label">生成时间</span>
            <input type="date" value={filters.date_from ?? ''} onChange={e => setFilters((p: TaskFilters) => ({ ...p, date_from: e.target.value || undefined }))} />
            <span className="muted">至</span>
            <input type="date" value={filters.date_to ?? ''} onChange={e => setFilters((p: TaskFilters) => ({ ...p, date_to: e.target.value || undefined }))} />
            <span className="filter-label" style={{ marginLeft: 18 }}>业务号</span>
            <input type="text" placeholder="搜索业务号" value={q} onChange={e => setQ(e.target.value)} />
            {(filters.authenticity || filters.risk || filters.parse || filters.bank || filters.date_from || filters.date_to || q) && (
              <button className="link-btn" type="button" onClick={() => { setFilters({}); setQ(''); }}>清空筛选</button>
            )}
          </div>
        </div>

        {error && <div className="notice error">{error}</div>}
        {!error && items.length === 0 && !loading && <p className="muted">没有符合条件的流水。调整筛选项，或让借款人先上传。</p>}

        {items.length > 0 && (
          <table className="mini list-table">
            <thead>
              <tr>
                <th>业务号</th><th>银行</th><th>账单期间</th><th>笔数</th>
                <th>流水合格性</th><th>信用风险</th><th>解析质量</th><th>材料</th><th>生成时间</th><th></th>
              </tr>
            </thead>
            <tbody>
              {items.map(t => {
                const riskTitle = t.risk.hits.map((h: { code: string | null }) => h.code ?? '').join('、');
                return (
                  <tr key={t.id} className="list-row" onClick={() => navigate('/report/' + t.id)}>
                    <td className="mono">{t.biz_no}</td>
                    <td>{t.bank_name ?? '未识别'}</td>
                    <td className="muted">{t.period_start ?? '—'} ~ {t.period_end ?? '—'}</td>
                    <td className="num">{t.parse.txn_count}</td>
                    <td><span className={'tag ' + t.authenticity.level}>{t.authenticity.label}</span></td>
                    <td title={riskTitle}><span className={'tag risk-' + t.risk.level}>{t.risk.label}</span>{t.risk.count > 0 && <span className="muted small"> {t.risk.count} 项</span>}</td>
                    <td><span className={'tag parse-' + t.parse.level}>{t.parse.label}</span><span className="muted small"> {t.parse.metrics_valued}/{t.parse.metrics_total}</span></td>
                    <td className="num">{t.materials}</td>
                    <td className="muted">{(t.created_at ?? '').replace('T', ' ').slice(0, 16)}</td>
                    <td><Link className="link-btn" to={'/report/' + t.id} onClick={(e: React.MouseEvent) => e.stopPropagation()}>查看报告 →</Link></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

