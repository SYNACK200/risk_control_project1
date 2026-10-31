import { Fragment, useEffect, useMemo, useState } from 'react';
import { getEntities, getMergeMethods, getMetricDefinitions, getThresholdDefinitions, mergeSubject,
  type EntitiesPayload, type MetricDef, type SubjectMergeMethod, type SubjectMergeResult, type ThresholdDef } from '../lib/api';

const GROUP_NAME: Record<string, string> = {
  A: '收入能力', B: '负债与还款', C: '资金与余额', D: '异常行为', E: '对手方与集中度',
};

const RISK_TEXT: Record<string, string> = { high: '高', medium: '中', low: '低', none: '未见' };

export function EntitiesPage() {
  const [data, setData] = useState<EntitiesPayload | null>(null);
  const [methods, setMethods] = useState<SubjectMergeMethod[]>([]);
  const [overlaps, setOverlaps] = useState<{ id: string; label: string; detail: string }[]>([]);
  const [subject, setSubject] = useState<string | null>(null);
  const [method, setMethod] = useState('net_internal');
  const [overlap, setOverlap] = useState('max');
  const [results, setResults] = useState<{ subject: string; data: SubjectMergeResult }[]>([]);
  const [active, setActive] = useState(0);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const result = results[active]?.data ?? null;
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [defs, setDefs] = useState<Record<string, MetricDef>>({});
  const [tdefs, setTdefs] = useState<ThresholdDef[]>([]);
  const [openMap, setOpenMap] = useState<Record<string, boolean>>({});

  useEffect(() => {
    getEntities()
      .then(d => {
        setData(d);
        setError('');
        const first = d.subjects.find(s => Object.keys(s.accounts).length > 1) ?? d.subjects[0];
        if (first?.holder_masked) setSubject(first.holder_masked);
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)));
    getMetricDefinitions()
      .then(d => setDefs(Object.fromEntries(d.items.map(i => [i.code, i]))))
      .catch(() => undefined);
    getThresholdDefinitions()
      .then(d => setTdefs(d.items))
      .catch(() => undefined);
    getMergeMethods()
      .then(d => { setMethods(d.methods); setOverlaps(d.overlap_modes); })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!subject) return;
    let alive = true;
    setLoading(true);
    mergeSubject(subject, method, overlap)
      .then(r => { if (alive) { setResults([{ subject: subject as string, data: r }]); setActive(0); setError(''); } })
      .catch(e => { if (alive) { setResults([]); setError(e instanceof Error ? e.message : String(e)); } })
      .finally(() => { if (alive) setLoading(false); });

  return () => { alive = false; };
  }, [subject, method, overlap]);

  const suggestionList = (data?.subjects ?? []).filter(
    s => s.holder_masked && Object.keys(s.accounts).length >= 2,
  );

  async function mergeMany(subjects: string[]) {
    if (!subjects.length) return;
    setLoading(true);
    setError('');
    const acc: { subject: string; data: SubjectMergeResult }[] = [];
    for (const name of subjects) {
      try {
        const r = await mergeSubject(name, method, overlap);
        acc.push({ subject: name, data: r });
      } catch (e) {
        setError((e instanceof Error ? e.message : String(e)) + '（' + name + '）');
      }
    }
    setResults(acc);
    setActive(0);
    setLoading(false);
  }

  const pickedNames = Object.entries(picked).filter(([, v]) => v).map(([k]) => k);

    const setOpenAll = (open: boolean) => {
    if (!result) return;
    setOpenMap(Object.fromEntries(result.metrics.map(m => [m.code, open])));
  };

  const groupedMetrics = useMemo(() => {
    if (!result) return [] as { name: string; items: SubjectMergeResult['metrics'] }[];
    const order = ['收入能力', '负债与还款', '资金与余额', '异常行为', '对手方与集中度'];
    const map = new Map<string, SubjectMergeResult['metrics']>();
    for (const m of result.metrics) {
      const raw = defs[m.code]?.group ?? '';
      const group = GROUP_NAME[raw] ?? (raw || '其他');
      if (!map.has(group)) map.set(group, []);
      map.get(group)!.push(m);
    }
    return [...map.entries()]
      .sort((a, b) => {
        const ia = order.findIndex(k => a[0].includes(k));
        const ib = order.findIndex(k => b[0].includes(k));
        return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
      })
      .map(([name, items]) => ({ name, items }));
  }, [result, defs]);

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

        <h3>系统建议合并的客户</h3>
        <p className="muted">系统把「同名下有多份流水」的客户列为怀疑对象；可以一次选多个一起合并，再逐个查看结果。</p>
        {suggestionList.length === 0 ? (
          <p className="muted">没有发现需要合并的同名多账户。若确有同一人的不同户名，请展开下方「特殊情况」手动处理。</p>
        ) : (
          <>
            <div className="suggest-list">
              {suggestionList.map(s => {
                const entries = Object.entries(s.accounts);
                const name = s.holder_masked as string;
                return (
                  <div className={"suggest-card" + (picked[name] ? " active" : "")} key={s.key}>
                    <div className="suggest-head">
                      <label className="suggest-pick">
                        <input type="checkbox" checked={Boolean(picked[name])}
                          onChange={e => setPicked(prev => ({ ...prev, [name]: e.target.checked }))} />
                        <strong>{name}</strong>
                      </label>
                      <span className="tag pass">{entries.length} 个账户</span>
                      <span className="muted small">共 {s.tasks.length} 份流水</span>
                      <span className="muted small">{entries.map(([k]) => k).join("、")}</span>
                    </div>
                    <div className="suggest-reason">
                      同一户名下有多份流水，建议合并成一份画像后再评价；不合并时，收入、负债与余额会被重复计算或低估。
                    </div>
                    <div className="suggest-actions">
                      <button className="pill-btn" type="button" onClick={() => { void mergeMany([name]); }}>只看这一个</button>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="suggest-bulk">
              <button className="pill-btn pill-btn-primary" type="button" disabled={loading}
                onClick={() => { void mergeMany(pickedNames.length ? pickedNames : suggestionList.map(s => s.holder_masked as string)); }}>
                {pickedNames.length ? "合并选中的 " + pickedNames.length + " 个" : "合并全部建议（" + suggestionList.length + " 个）"}
              </button>
              <span className="muted small">合并后会用上方「口径」逐个计算，可在结果区切换查看</span>
            </div>
          </>
        )}

        <details className="manual-merge">
        <summary>特殊情况：手动选择客户与合并方式</summary>
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

        <h3>按什么口径评价（先想清楚要回答哪个问题）</h3>
        <div className="method-cards">
          {methods.filter(m => (m.tier ?? 'advanced') === 'primary').map(m => (
            <button key={m.id} type="button"
              className={'method-card' + (method === m.id ? ' active' : '')}
              onClick={() => setMethod(m.id)}>
              <span className="method-label">{m.label}</span>
              <span className="method-question">{m.question ?? m.short}</span>
            </button>
          ))}
        </div>

        <details className="more-methods">
          <summary>更多口径（特殊情况才用）</summary>
          <div className="method-cards">
            {methods.filter(m => (m.tier ?? 'advanced') !== 'primary').map(m => (
              <button key={m.id} type="button"
                className={'method-card' + (method === m.id ? ' active' : '')}
                onClick={() => setMethod(m.id)}>
                <span className="method-label">{m.label}</span>
                <span className="method-question">{m.question ?? m.short}</span>
              </button>
            ))}
          </div>
          {overlaps.length > 1 && (
            <div className="filter-row" style={{ marginTop: 8 }}>
              <span className="filter-label">重叠月份处理</span>
              <select value={overlap} onChange={e => setOverlap(e.target.value)}>
                {overlaps.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
            </div>
          )}
        </details>

        {current && (
          <div className="method-explain">
            <div><span className="me-k">回答的问题</span><span className="me-v">{current.question ?? current.short}</span></div>
            <div><span className="me-k">会怎么做</span><span className="me-v">{current.approach ?? current.detail}</span></div>
            <div><span className="me-k">对结论的影响</span><span className="me-v">{current.impact ?? current.formula}</span></div>
            <div><span className="me-k">什么时候选它</span><span className="me-v">{current.when_to_use ?? current.assumption}</span></div>
          </div>
        )}

        </details>

        {error && <div className="notice error">{error}</div>}
        {loading && <p className="muted">正在合并…</p>}

        {results.length > 1 && (
          <div className="merge-result-tabs">
            <span className="muted small">已合并 {results.length} 个对象：</span>
            {results.map((r, i) => (
              <button key={r.subject + i} type="button"
                className={'pill-btn' + (i === active ? ' pill-btn-primary' : '')}
                onClick={() => setActive(i)}>
                {r.subject} · 风险 {RISK_TEXT[r.data.risk.level] ?? r.data.risk.level}
              </button>
            ))}
          </div>
        )}

        {result && !loading && (
          <section style={{ marginTop: 16 }}>
            {result.sync && result.sync.sync_months.length > 0 && (
              <div className="notice info">
                同步放大：{result.sync.sync_months.length} / {result.sync.months} 个月出现多账户同时大额流出，
                系数 ×{result.sync.amplify_factor}（超可加：合并风险高于简单相加）
              </div>
            )}
            <div className="merge-head">
              <span className={'tag risk-' + result.risk.level}>信用风险 {RISK_TEXT[result.risk.level] ?? result.risk.level}</span>
              <span className="muted">命中 {result.risk.hits} 项 · 覆盖 {result.coverage.months} 个月（{result.coverage.from} ~ {result.coverage.to}）· 重叠 {result.coverage.overlap_months.length} 个月</span>
            </div>

            <div className="metric-toolbar">
              <span className="muted small">共 {result.metrics.length} 项 · 点任意一行看「口径 / 标准参考 / 本次合并怎么算」</span>
              <button className="pill-btn" type="button" onClick={() => setOpenAll(true)}>展开全部</button>
              <button className="pill-btn" type="button" onClick={() => setOpenAll(false)}>全部收起</button>
            </div>

            {groupedMetrics.map(g => (
              <div className="metric-group" key={g.name}>
                <div className="metric-group-head">
                  <span className="metric-group-name">{g.name}</span>
                  <span className="muted small">{g.items.length} 项</span>
                </div>
                <table className="mini metric-table">
                  <thead><tr><th></th><th>指标</th><th>合并值</th><th>单位</th><th>怎么来的</th></tr></thead>
                  <tbody>
                    {g.items.map(m => {
                      const def = defs[m.code];
                      const open = Boolean(openMap[m.code]);
                      const gname = def ? (GROUP_NAME[def.group] ?? def.group) : '';
                      const refs = gname ? tdefs.filter(t => t.group === gname) : [];
                      return (
                        <Fragment key={m.code}>
                          <tr
                            className={'metric-row' + (open ? ' open' : '')}
                            onClick={() => setOpenMap(prev => ({ ...prev, [m.code]: !prev[m.code] }))}
                          >
                            <td className="caret">{open ? '▾' : '▸'}</td>
                            <td>{m.name} <span className="muted small">{m.code}</span></td>
                            <td className="num">{m.value === null ? '不可算' : m.value.toLocaleString()}</td>
                            <td>{m.unit}</td>
                            <td className="muted">{m.how}</td>
                          </tr>
                          {open && (
                            <tr className="metric-detail-row">
                              <td />
                              <td colSpan={4}>
                                <div className="me-grid">
                                  <div><span className="me-k">所属分区</span><span className="me-v">{def ? (GROUP_NAME[def.group] ?? def.group) : "未分组"}</span></div>
                                  <div><span className="me-k">计算公式</span><span className="me-v mono">{def?.formula ?? "—"}</span></div>
                                  <div><span className="me-k">输入字段</span><span className="me-v">{def?.inputs ?? "—"}</span></div>
                                  <div><span className="me-k">本次合并口径</span><span className="me-v">{m.how}</span></div>
                                  <div><span className="me-k">备注</span><span className="me-v">{m.note || "—"}</span></div>
                                </div>
                                <div className="metric-ref">
                                  <div className="metric-ref-title">标准参考（阈值口径）</div>
                                  {refs.length === 0 ? (
                                    <div className="muted small">该指标所在分区没有可调阈值，仅作参考展示。</div>
                                  ) : (
                                    <ul className="metric-ref-list">
                                      {refs.map(t => (
                                        <li key={t.key}>
                                          <span className="me-k">{t.label}</span>
                                          <span className="me-v">{t.desc}</span>
                                          <span className="muted small">默认 {t.default}{t.unit ? " " + t.unit : ""} · 影响 {t.impacts.join("、") || "—"}</span>
                                        </li>
                                      ))}
                                    </ul>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ))}

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

