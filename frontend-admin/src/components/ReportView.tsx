import { Fragment, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { downloadAttachment, getMetricDefinitions, getReport, getTask, getTransactions, getVerificationDefinitions, listTemplates, reanalyzeTask, reanalyzeWithTemplate, whitelistTask, type MetricDef, type PrereadInfo, type ReportPayload, type TemplateRow, type TxnRow } from '../lib/api';
import { InsightSection } from './Charts';
import { MetricExplain } from './MetricExplain';
import { CheckTable } from './CheckTable';

const METRIC_GROUPS = [
  { key: 'income', prefix: 'A', name: '收入能力' },
  { key: 'debt', prefix: 'B', name: '负债与还款' },
  { key: 'cash', prefix: 'C', name: '资金与余额' },
  { key: 'abnormal', prefix: 'D', name: '异常行为' },
  { key: 'counterparty', prefix: 'E', name: '对手方与集中度' },
];

const LAYER_NAMES: Record<string, string> = { file: '载体层', content: '内容层', ledger: '账务层', external: '外部层' };

type AuthLevel = 'pass' | 'grant' | 'supplement' | 'fail' | 'unknown';

const AUTH_LABEL: Record<AuthLevel, string> = {
  pass: '已通过真实性校验',
  grant: '可授信（核心层通过，外部数据受限）',
  supplement: '需补充（核心层有受限项）',
  fail: '未通过真实性校验',
  unknown: '无法判定（核验受限）',
};

function authenticity(layers: { layer: string; status: string }[], carrier: string, limitations: string[]) {
  const statusOf = (name: string) => layers.find(l => l.layer === name)?.status ?? 'unavailable';
  const anyBad = layers.some(l => l.status === 'inconsistent');
  const allPass = ['file', 'content', 'ledger', 'external'].every(n => statusOf(n) === 'pass');
  const corePass = ['file', 'content', 'ledger'].every(n => statusOf(n) === 'pass');
  let level: AuthLevel = allPass ? 'pass' : anyBad ? 'fail' : corePass ? 'grant' : 'supplement';
  if (carrier === 'screenshot') level = 'fail';
  if (carrier === 'image') level = 'unknown';
  const blocked = layers.filter(l => l.status !== 'pass').map(l => LAYER_NAMES[l.layer] ?? l.layer);
  return { level, label: AUTH_LABEL[level], blocked, limited: limitations.length };
}


export function ReportView({ taskId }: { taskId: number }) {
  const [report, setReport] = useState<ReportPayload | null>(null);
  const [txns, setTxns] = useState<TxnRow[]>([]);
  const [error, setError] = useState('');
  const [defs, setDefs] = useState<Record<string, MetricDef>>({});
  const [openMetric, setOpenMetric] = useState<string | null>(null);
  const [vmethods, setVmethods] = useState<Record<string, string>>({});
  const [preread, setPreread] = useState<PrereadInfo | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [openLayers, setOpenLayers] = useState<Record<string, boolean>>({});
  const [openSelf, setOpenSelf] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const [templates, setTemplates] = useState<TemplateRow[]>([]);
  const [templateId, setTemplateId] = useState<string>('');
  const [whitelist, setWhitelist] = useState<{ reason: string; at: string } | null>(null);
  const [note, setNote] = useState('');

  useEffect(() => {
    let alive = true;
    setReport(null);
    setError('');
    Promise.all([getReport(taskId), getTransactions(taskId), getTask(taskId)])
      .then(([rep, rows, task]) => {
        if (!alive) return;
        setReport(rep);
        setTxns(rows);
        setPreread(task.check_result?.preread ?? null);
        const wl = (task.check_result as Record<string, unknown> | undefined)?.whitelist as
          { reason: string; at: string } | undefined;
        setWhitelist(wl ?? null);
      })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [taskId]);

  useEffect(() => {
    listTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    getVerificationDefinitions()
      .then(d => setVmethods(Object.fromEntries(d.items.map(i => [i.code, i.method]))))
      .catch(() => setVmethods({}));
    getMetricDefinitions()
      .then(d => setDefs(Object.fromEntries(d.items.map(i => [i.code, i]))))
      .catch(() => setDefs({}));
  }, []);

  async function reanalyzeWithTpl() {
    setError('');
    setNote('');
    try {
      const password = window.prompt('加密件请再输一次打开口令；没有就点确定。') ?? '';
      const id = templateId ? Number(templateId) : null;
      await reanalyzeWithTemplate(taskId, id, password || undefined);
      const rep = await getReport(taskId);
      setReport(rep);
      setNote(id ? '已用所选模板重新解析' : '已用通用解析（无模板）重新解析');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function markWhitelist() {
    const reason = window.prompt('开绿灯的理由（会写入审计）：', '我方自造测试数据，已人工确认') ?? '';
    if (!reason) return;
    try {
      await whitelistTask(taskId, reason);
      setWhitelist({ reason, at: new Date().toISOString().slice(0, 19) });
      setNote('已开绿灯，后续不再按解析失败阻断');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function reanalyze() {
    setError('');
    try {
      const password = window.prompt('如果这份文件有打开口令，请输入；没有就点确定留空。') ?? '';
      await reanalyzeTask(taskId, password || undefined);
      const rep = await getReport(taskId);
      setReport(rep);
      setDetailOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function exportCsv() {
    setError('');
    try {
      await downloadAttachment('/tasks/' + taskId + '/transactions.csv', 'task-' + taskId + '.csv');
      setNote('明细已导出（CSV）');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function exportJson() {
    setError('');
    try {
      await downloadAttachment('/tasks/' + taskId + '/export.json', 'task-' + taskId + '.json');
      setNote('完整报告已导出（JSON）');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function printReport() {
    window.print();
  }

  function toggleLayer(layer: string) {
    setOpenLayers(prev => ({ ...prev, [layer]: !prev[layer] }));
  }

  return (
    <div className="result-wrap">
      <div className="result">
        <div className="result-head sticky-head">
          <div className="result-head-left">
            <Link className="back-btn" to="/">← 返回解析结果</Link>
            <h2>报告详情</h2>
          </div>
        </div>
        {error && <div className="notice error">{error}</div>}
        {!report && !error && <p className="muted">正在读取报告…</p>}
        {report && (
          <section style={{ marginTop: 22 }}>
            <div className={`verdict-card ${report.verdict === '未发现异常' ? 'ok' : 'bad'}`}>
              <div className="verdict-title">{report.verdict}</div>
              <div className="verdict-reason">{report.verdict_reason}</div>
            </div>
            <div className="reanalyze-bar">
              <span className="filter-label">解析模板</span>
              <select value={templateId} onChange={e => setTemplateId(e.target.value)}>
                <option value="">通用解析（无模板）</option>
                {templates.map(tpl => (
                  <option key={tpl.id} value={String(tpl.id)}>{tpl.bank_code} v{tpl.version}</option>
                ))}
              </select>
              <button className="btn" type="button" onClick={() => { void reanalyzeWithTpl(); }}>重新解析</button>
              <button className="btn secondary" type="button" onClick={() => { void exportCsv(); }}>导出明细 CSV</button>
              <button className="btn secondary" type="button" onClick={() => { void exportJson(); }}>导出报告 JSON</button>
              <button className="btn secondary" type="button" onClick={printReport}>打印 / 存为 PDF</button>
              {!whitelist && (
                <button className="btn" type="button" onClick={() => { void markWhitelist(); }}>开绿灯（人工放行）</button>
              )}
              {note && <span className="muted">{note}</span>}
            </div>
            {whitelist && (
              <div className="notice ok">
                已开绿灯（白名单）：{whitelist.reason} · {whitelist.at}
              </div>
            )}
            <p className="muted">载体 {report.carrier} · 指标集 v{report.metric_set_version} · 阈值 v{report.threshold_version} · 材料 {report.materials.length} 份</p>

            {(() => {
              const a = authenticity(report.layers, report.carrier, report.limitations);
              return (
                <div className={"auth-card " + a.level}>
                  <div className="auth-line auth-toggle" onClick={() => setAuthOpen(v => !v)} role="button" tabIndex={0}>
                    <span className="auth-badge">{a.level === 'pass' ? '✓' : a.level === 'fail' ? '✕' : '!'}</span>
                    <span className="auth-title">真实性校验：{a.label}</span>
                    <span className="auth-caret">{authOpen ? "▾" : "▸"}</span>
                    <span className="auth-meta">载体 {report.carrier} · 受限 {a.limited} 项 · {a.blocked.length ? '未全通过：' + a.blocked.join('、') : '四层全部通过'}</span>
                  </div>
                  <div className="auth-meta-line" hidden={!authOpen}>
                    <button
                      className="pill-btn pill-btn-primary"
                      type="button"
                      onClick={() => setOpenLayers(Object.fromEntries(report.layers.map(l => [l.layer, true])))}
                    ><span className="pill-icon">▣</span>展开四层逐项（36 项）</button>
                    <button
                      className="pill-btn"
                      type="button"
                      onClick={() => setOpenLayers({})}
                    ><span className="pill-icon">▤</span>全部收起</button>
                  </div>
                  {authOpen && (
                  <div className="auth-inline-layers">
                <h3>四层核验（点卡片展开，逐项看「怎么验」与本次结果）</h3>
                {!report.layers.some(l => (l.checks?.length ?? 0) > 0) && (
                  <p className="me-warn">
                    这份报告生成于逐项明细上线之前（v2.4.0 以前），只有层结论、没有逐项结果。
                    点「重算逐项结果」用原文件补齐；加密件重算需要再输一次口令。
                    <button className="link-btn" type="button" onClick={() => { void reanalyze(); }}>重算逐项结果 ▸</button>
                  </p>
                )}
                {report.layers.map(l => {
                  const items = l.checks ?? [];
                  const cnt = (st: string) => items.filter(i => i.status === st).length;
                  const open = Boolean(openLayers[l.layer]);
                  return (
                    <div key={l.layer} className={'check-card' + (open ? ' open' : '')}>
                      <button type="button" className="card-head" onClick={() => toggleLayer(l.layer)} aria-expanded={open}>
                        <span className={'check-status ' + l.status}>{l.status}</span>
                        <strong>{LAYER_NAMES[l.layer] ?? l.layer}</strong>
                        <span className="muted card-summary">
                          {items.length} 项：通过 {cnt('pass')} · 部分/受限 {cnt('partial') + cnt('limited')} · 未执行 {cnt('skipped')} · 不通过 {cnt('fail') + cnt('inconsistent')}
                        </span>
                        <span className="card-caret">{open ? '▾ 收起' : '▸ 展开'}</span>
                      </button>
                      {open && (
                        <div className="card-body">
                          <div className="muted layer-detail">{l.detail}</div>
                          <CheckTable items={items} methods={vmethods} />
                        </div>
                      )}
                    </div>
                  );
                })}
                  </div>
                  )}
                </div>
              );
            })()}


            {report.scores && (
              <div className="scores-section">
                <div className="scores-head">
                  <span className="scores-title">综合评分</span>
                  <span className={"score-grade " + report.scores.grade}>{report.scores.grade_label}</span>
                  <span className="score-total">{report.scores.overall.toFixed(1)}<span className="muted small"> / 100</span></span>
                </div>
                <div className="scores-domains">
                  {report.scores.domains.map(d => (
                    <div className="score-card" key={d.key}>
                      <div className="score-card-head">
                        <span className="score-name">{d.name}</span>
                        <span className="score-val">{d.score.toFixed(1)}</span>
                      </div>
                      <div className="score-bar"><div className={"score-fill " + d.key} style={{ width: d.score + "%" }} /></div>
                      <div className="muted small">{d.desc}</div>
                      <div className="score-detail">{d.detail}</div>
                      <div className="muted small">权重 {(d.weight * 100).toFixed(0)}% · 指标 {d.metric_valued}/{d.metric_total} 有值</div>
                    </div>
                  ))}
                </div>
                <div className="muted small">{report.scores.method}</div>
              </div>
            )}

            {preread && (
              <div className={"preread-card " + preread.verdict}>
                <div className="preread-head">
                  <span className="preread-title">预读取（不看模板，只读全文）</span>
                  <span className={'check-status ' + (preread.verdict === 'accept' ? 'pass' : preread.verdict === 'reject' ? 'fail' : 'limited')}>
                    {preread.verdict === 'accept' ? '判定为流水' : preread.verdict === 'reject' ? '判定非流水' : '需人工确认'}
                  </span>
                  <span className="muted">置信度 {preread.confidence.toFixed(2)}</span>
                </div>
                <div className="preread-grid">
                  <div><span className="me-k">银行</span><span className="me-v">{preread.bank_name ?? '未识别'}（{preread.bank_code ?? '—'}）</span></div>
                  <div><span className="me-k">账户 / 户名</span><span className="me-v">{preread.account_masked ?? '—'} / {preread.holder_masked ?? '—'}</span></div>
                  <div><span className="me-k">预读期间</span><span className="me-v">{preread.period_start ?? '—'} ~ {preread.period_end ?? '—'}</span></div>
                  <div><span className="me-k">页数 / 文字层</span><span className="me-v">{preread.pages} 页 / {preread.has_text_layer ? '有' : '无'}</span></div>
                  <div><span className="me-k">预读疑似明细行</span><span className="me-v">{preread.txn_like_rows} 行（命中金额 {preread.amounts_found} 处）</span></div>
                  <div><span className="me-k">与模板解析对照</span><span className="me-v">见下方自检 S8</span></div>
                </div>
                {preread.keyword_hits.length > 0 && (
                  <p className="muted">命中流水特征：{preread.keyword_hits.slice(0, 8).join('、')}</p>
                )}
                {preread.reasons.length > 0 && <p className="me-warn">{preread.reasons.join('；')}</p>}
              </div>
            )}

            <h3>阈值提示</h3>
            {report.conclusions.length === 0 ? <p className="muted">未触发</p> : (
              <div className="conclusions">
                {report.conclusions.map(c => (
                  <div key={c.code} className="conclusion info">
                    <div className="c-title">{c.code}</div>
                    <div className="c-meta">阈值 {c.threshold} · 实际 {c.value}</div>
                  </div>
                ))}
              </div>
            )}

            <InsightSection txns={txns} />

            <h3>指标（{report.metrics.filter(m => m.value !== null).length}/{report.metrics.length} 有值）</h3>
            <p className="muted">按业务域分块；点任意一行展开：看这条指标怎么算、用了哪些输入、按原始数据画出来的图。</p>
            {METRIC_GROUPS.map(g => {
              const items = report.metrics.filter(m => m.code.startsWith(g.prefix));
              const score = report.scores?.domains.find(d => d.key === g.key);
              return (
                <div className="metric-group" key={g.key}>
                  <div className="metric-group-head">
                    <span className="metric-group-name">{g.name}</span>
                    <span className="muted small">{g.prefix} 类 · {items.filter(m => m.value !== null).length}/{items.length} 有值</span>
                    {score && <span className={"metric-group-score " + score.key}>{score.score.toFixed(1)} 分</span>}
                  </div>
                  <table className="mini metric-table">
                    <thead><tr><th></th><th>编码</th><th>指标</th><th>值</th><th>单位</th><th>口径说明</th></tr></thead>
                    <tbody>
                      {items.map(m => (
                        <Fragment key={m.code}>
                          <tr
                            className={'metric-row' + (openMetric === m.code ? ' open' : '')}
                            onClick={() => setOpenMetric(openMetric === m.code ? null : m.code)}
                          >
                            <td className="caret">{openMetric === m.code ? '▾' : '▸'}</td>
                            <td className="mono">{m.code}</td><td>{m.name}</td>
                            <td className="num">{m.value ?? '不可算'}</td><td>{m.unit ?? '—'}</td>
                            <td className="muted">{m.note ?? '—'}</td>
                          </tr>
                          {openMetric === m.code && (
                            <tr className="metric-detail-row">
                              <td />
                              <td colSpan={5}>
                                <MetricExplain metric={m} def={defs[m.code]} trend={report.trend ?? []} txns={txns} metricSetVersion={report.metric_set_version} />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })}


            <div className={'check-card' + (openSelf ? ' open' : '')}>
              <button type="button" className="card-head" onClick={() => setOpenSelf(v => !v)} aria-expanded={openSelf}>
                <strong>识别自检（S0–S8）</strong>
                <span className="muted card-summary">检查「系统有没有把这份文件读对」，与伪造判断分开看 · {(report.self_check ?? []).length} 项</span>
                <span className="card-caret">{openSelf ? '▾ 收起' : '▸ 展开'}</span>
              </button>
              {openSelf && (
                <div className="card-body">
                  <CheckTable items={report.self_check ?? []} methods={vmethods} />
                </div>
              )}
            </div>

            <details className="auth-detail" open={detailOpen} onToggle={e => setDetailOpen((e.target as HTMLDetailsElement).open)}>
              <summary>核验受限与证据（点开看细节）</summary>
            <h3>核验受限（{report.limitations.length}）</h3>
            <ul className="muted">{report.limitations.map((x, i) => <li key={i}>{x}</li>)}</ul>

            <h3>证据（{report.evidence.length}）</h3>
            {report.evidence.length === 0 ? <p className="muted">本报告无证据项。</p> : (
              <table className="mini">
                <thead><tr><th>交易</th><th>规则</th><th>页码</th><th>坐标</th></tr></thead>
                <tbody>
                  {report.evidence.slice(0, 50).map((e, i) => (
                    <tr key={i}><td className="mono">{e.txn_id ?? '—'}</td><td className="mono">{e.rule_code}</td><td>{e.page_no}</td><td className="mono">{e.x.toFixed(4)}, {e.y.toFixed(4)}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
            </details>
          </section>
        )}
      </div>
    </div>
  );
}

