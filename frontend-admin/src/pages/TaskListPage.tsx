import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listTasks, purgeTasks, recycleTasks, restoreTasks, type TaskFacets, type TaskFilters, type TaskSummary, type TaskSummaryList } from '../lib/api';

const AUTH: Record<string, string> = { pass: '合格', grant: '可授信', supplement: '需补充', fail: '不合格', unknown: '无法判定' };
const SRC: Record<string, string> = { clean: '未见可疑', limited: '受限', suspicious: '来源可疑', unknown: '无法判定' };
const RISK: Record<string, string> = { none: '未见', low: '低', medium: '中', high: '高' };
const PARSE: Record<string, string> = { ok: '完整', partial: '不完整', failed: '失败' };

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" className={'filter-chip' + (active ? ' active' : '')} onClick={onClick}>{children}</button>;
}

function money(value: string | null | undefined) {
  if (!value) return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
}

export function TaskListPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<TaskSummaryList | null>(null);
  const [filters, setFilters] = useState<TaskFilters>({});
  const [q, setQ] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<'live' | 'trash'>('live');
  const [selected, setSelected] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState<'recycle' | 'restore' | 'purge' | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    listTasks({ ...filters, trash: view === 'trash' ? 1 : 0, q: q || undefined })
      .then(d => { if (alive) { setData(d); setError(''); } })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [filters, q, view]);

  const items: TaskSummary[] = data?.items ?? [];
  const facets: TaskFacets = data?.facets ?? { authenticity: {}, source: {}, risk: {}, parse: {}, bank: {}, total: 0 };
  const riskCodes = useMemo(() => {
    const set = new Set<string>();
    items.forEach(i => (i.risk_codes || []).forEach(c => { if (c) set.add(c); }));
    return Array.from(set).sort();
  }, [items]);

  const allChecked = items.length > 0 && selected.length === items.length;
  const toggleSelect = (id: number) => setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  const toggleAll = () => setSelected(allChecked ? [] : items.map(i => i.id));

  const ACTION_LABEL: Record<'recycle' | 'restore' | 'purge', string> = {
    recycle: '移入回收站', restore: '恢复', purge: '彻底删除（不可恢复）',
  };

  async function runAction(kind: 'recycle' | 'restore' | 'purge') {
    if (selected.length === 0) return;
    const label = ACTION_LABEL[kind];
    setPending(null);
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const ids = [...selected];
      const res = kind === 'recycle' ? await recycleTasks(ids)
        : kind === 'restore' ? await restoreTasks(ids) : await purgeTasks(ids);
      const done = (res as { moved?: number; restored?: number; purged?: number });
      const count = done.moved ?? done.restored ?? done.purged ?? ids.length;
      setMessage(label + '完成：' + count + ' 条');
      setSelected([]);
      setFilters(prev => ({ ...prev }));
      const fresh = await listTasks({ ...filters, trash: view === 'trash' ? 1 : 0, q: q || undefined });
      setData(fresh);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const set = (patch: TaskFilters) => setFilters(prev => ({ ...prev, ...patch }));
  const toggle = (key: keyof TaskFilters, value: string) =>
    set({ [key]: (filters as Record<string, unknown>)[key] === value ? undefined : value } as TaskFilters);

  return (
    <div className="result-wrap">
      <div className="result">
        <div className="result-head">
          <h2>{view === 'trash' ? '回收站' : '解析结果'}</h2>
          <div className="tabs-inline">
            <button type="button" className={'chip-btn' + (view === 'live' ? ' active' : '')} onClick={() => { setView('live'); setSelected([]); }}>流水列表</button>
            <button type="button" className={'chip-btn' + (view === 'trash' ? ' active' : '')} onClick={() => { setView('trash'); setSelected([]); }}>回收站</button>
          </div>
          <span className="muted">{loading ? '加载中…' : '共 ' + (data?.total ?? 0) + ' 条'}</span>
        </div>
        {message && <div className="notice ok">{message}</div>}
        {selected.length > 0 && (
          <div className="bulk-bar">
            <span>已选 {selected.length} 条</span>
            {view === 'live' ? (
              <button className="btn" type="button" disabled={busy} onClick={() => setPending('recycle')}>移入回收站</button>
            ) : (
              <>
                <button className="btn" type="button" disabled={busy} onClick={() => setPending('restore')}>恢复</button>
                <button className="btn danger" type="button" disabled={busy} onClick={() => setPending('purge')}>彻底删除</button>
              </>
            )}
            <button className="link-btn" type="button" onClick={() => setSelected([])}>取消选择</button>
            {pending && (
              <span className="bulk-confirm">
                确定{ACTION_LABEL[pending]} {selected.length} 条？
                <button className="btn" type="button" disabled={busy} onClick={() => { void runAction(pending); }}>确认</button>
                <button className="link-btn" type="button" onClick={() => setPending(null)}>再想想</button>
              </span>
            )}
          </div>
        )}
        {error && <div className="notice error">{error}</div>}

        <div className="filter-panel">
          <div className="filter-row">
            <span className="filter-label">流水合格性</span>
            <Chip active={!filters.authenticity} onClick={() => set({ authenticity: undefined })}>全部</Chip>
            {(['pass', 'grant', 'supplement', 'fail', 'unknown'] as const).map(level => (
              <Chip key={level} active={filters.authenticity === level} onClick={() => toggle('authenticity', level)}>
                {AUTH[level]} {facets.authenticity?.[level] ?? 0}
              </Chip>
            ))}
          </div>
          <div className="filter-row">
            <span className="filter-label">原始文件真实性</span>
            <Chip active={!filters.source} onClick={() => set({ source: undefined })}>全部</Chip>
            {(['clean', 'limited', 'suspicious', 'unknown'] as const).map(level => (
              <Chip key={level} active={filters.source === level} onClick={() => toggle('source', level)}>
                {SRC[level]} {facets.source?.[level] ?? 0}
              </Chip>
            ))}
          </div>
          <div className="filter-row">
            <span className="filter-label">信用风险</span>
            <Chip active={!filters.risk} onClick={() => set({ risk: undefined })}>全部</Chip>
            {(['none', 'low', 'medium', 'high'] as const).map(level => (
              <Chip key={level} active={filters.risk === level} onClick={() => toggle('risk', level)}>
                {RISK[level]} {facets.risk?.[level] ?? 0}
              </Chip>
            ))}
            <select className="filter-select" value={filters.risk_code ?? ''} onChange={e => set({ risk_code: e.target.value || undefined })}>
              <option value="">按风险项筛</option>
              {riskCodes.map(code => <option key={code} value={code}>{code}</option>)}
            </select>
          </div>
          <div className="filter-row">
            <span className="filter-label">解析质量</span>
            <Chip active={!filters.parse} onClick={() => set({ parse: undefined })}>全部</Chip>
            {(['ok', 'partial', 'failed'] as const).map(level => (
              <Chip key={level} active={filters.parse === level} onClick={() => toggle('parse', level)}>
                {PARSE[level]} {facets.parse?.[level] ?? 0}
              </Chip>
            ))}
            <select className="filter-select" value={filters.bank ?? ''} onChange={e => set({ bank: e.target.value || undefined })}>
              <option value="">全部银行</option>
              {(facets.bank ? Object.keys(facets.bank) : []).map(bank => <option key={bank} value={bank}>{bank}</option>)}
            </select>
          </div>
          <div className="filter-row">
            <span className="filter-label">时间</span>
            <input className="filter-input" type="date" value={filters.date_from ?? ''} onChange={e => set({ date_from: e.target.value || undefined })} />
            <span className="muted">至</span>
            <input className="filter-input" type="date" value={filters.date_to ?? ''} onChange={e => set({ date_to: e.target.value || undefined })} />
            <span className="filter-label" style={{ marginLeft: 18 }}>期间收入</span>
            <input className="filter-input narrow" type="number" placeholder="最小" value={filters.min_income ?? ''} onChange={e => set({ min_income: e.target.value ? Number(e.target.value) : undefined })} />
            <span className="muted">~</span>
            <input className="filter-input narrow" type="number" placeholder="最大" value={filters.max_income ?? ''} onChange={e => set({ max_income: e.target.value ? Number(e.target.value) : undefined })} />
            <input className="filter-input" placeholder="业务号/关键字" value={q} onChange={e => setQ(e.target.value)} />
            <button type="button" className="btn" onClick={() => { setFilters({}); setQ(''); }}>重置</button>
          </div>
        </div>

        {items.length === 0 && !loading ? (
          <p className="muted">{view === 'trash' ? '回收站是空的。' : '没有符合条件的解析结果。'}</p>
        ) : (
          <table className="mini list-table">
            <thead>
              <tr>
                <th style={{ width: 32 }}><input type="checkbox" checked={allChecked} onChange={toggleAll} /></th>
                <th>业务号</th><th>银行</th><th>账期</th><th>笔数</th>
                <th>期间收入</th><th>月均收入</th><th>DTI</th>
                <th>流水合格性</th><th>原始文件</th><th>信用风险</th><th>解析质量</th>
                <th>受限</th><th>生成时间</th>
              </tr>
            </thead>
            <tbody>
              {items.map(t => (
                <tr key={t.id} className="list-row" onClick={() => navigate('/report/' + t.id)}>
                  <td onClick={e => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.includes(t.id)} onChange={() => toggleSelect(t.id)} />
                  </td>
                  <td className="mono">{t.biz_no}</td>
                  <td>{t.bank_name ?? '未识别'}</td>
                  <td className="muted">{t.period_start ?? '—'} ~ {t.period_end ?? '—'}</td>
                  <td className="num">{t.parse.txn_count}</td>
                  <td className="num">{money(t.income)}</td>
                  <td className="num">{money(t.monthly_income)}</td>
                  <td className="num">{t.dti ?? '—'}</td>
                  <td title={(t.authenticity.missing_materials || []).length > 0
                    ? '缺材料：' + (t.authenticity.missing_materials || []).join('、')
                    : (t.authenticity.limited_layers || []).join('、')}>
                    <span className={'tag ' + t.authenticity.level}>{t.authenticity.label}</span>
                  </td>
                  <td><span className={'tag src-' + t.source.level}>{t.source.label}</span></td>
                  <td title={(t.risk_codes || []).join('、')}>
                    <span className={'tag risk-' + t.risk.level}>{t.risk.label}</span>
                    {t.risk.count > 0 && <span className="muted small"> {t.risk.count} 项</span>}
                  </td>
                  <td>
                    <span className={'tag parse-' + t.parse.level}>{t.parse.label}</span>
                    <span className="muted small"> {t.parse.metrics_valued}/{t.parse.metrics_total}</span>
                  </td>
                  <td className="num">{t.limitations}</td>
                  <td className="muted">{t.created_at?.slice(0, 16).replace('T', ' ') ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
