import { useCallback, useEffect, useState } from 'react';
import {
  getEntities,
  getEntitiesMerge,
  getMergeMethods,
  mergeTasks,
  resolveEntityConflict,
  undoEntityConflict,
  type EntitiesPayload,
  type MergeMethodInfo,
} from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';

type ConflictItem = {
  account_key?: string;
  account_masked?: string;
  bank_name?: string;
  holders?: string[];
  tasks?: number[];
  message?: string;
  resolved?: boolean;
  resolution?: { subject: string; note?: string | null; at?: string | null } | null;
};

type MergeResult = {
  subject?: string;
  method?: { id: string; label: string; short: string; formula: string };
  coverage?: {
    months?: number;
    overlap_months?: string[];
    from?: string;
    to?: string;
    raw_txn_count?: number;
    merged_txn_count?: number;
    dropped_duplicates?: number;
    internal_transfers?: number;
  };
  accounts?: {
    task_id: number;
    bank_name?: string;
    account_masked?: string;
    months?: number;
    txn_count?: number;
    balance_end?: string | null;
    risk_hits?: number;
    verdict?: string | null;
  }[];
  metrics?: { code: string; name: string; value: number | string | null; unit: string; how?: string; note?: string }[];
  risk?: { level?: string; hits?: number };
  unsupported?: { code: string; name: string; reason: string }[];
  warnings?: string[];
  explain?: Record<string, string>;
};

function formatMetricValue(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const num = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(num) ? num.toFixed(2) : String(value);
}

function normalizeMergeResult(raw: unknown, fallbackMethod: string, labelHint?: string): MergeResult {
  const obj = (raw ?? {}) as Record<string, unknown>;
  // GET /entities/merge 已是嵌套结构；POST /tasks/merge 返回平铺结构 {mode, label, formula, raw_txn_count, txn_count, ...}
  if (obj.coverage || obj.method) {
    return obj as MergeResult;
  }
  const modeId = String(obj.mode || fallbackMethod);
  const rawMetrics = Array.isArray(obj.metrics) ? (obj.metrics as Record<string, unknown>[]) : [];
  return {
    subject: labelHint || '指定任务集',
    method: {
      id: modeId,
      label: String(obj.label || modeId),
      short: '',
      formula: String(obj.formula || ''),
    },
    coverage: {
      raw_txn_count: typeof obj.raw_txn_count === 'number' ? obj.raw_txn_count : undefined,
      merged_txn_count: typeof obj.txn_count === 'number' ? obj.txn_count : undefined,
      dropped_duplicates: typeof obj.dropped_duplicates === 'number' ? obj.dropped_duplicates : 0,
      internal_transfers: typeof obj.internal_transfers === 'number' ? obj.internal_transfers : 0,
    },
    metrics: rawMetrics.map((m) => ({
      code: String(m.code || ''),
      name: String(m.name || ''),
      value: (m.value as number | string | null) ?? null,
      unit: String(m.unit || ''),
      how: String(m.how || m.note || ''),
    })),
    warnings: Array.isArray(obj.notes) ? (obj.notes as string[]) : [],
  };
}

export default function EntitiesPage() {
  const [data, setData] = useState<EntitiesPayload | null>(null);
  const [methods, setMethods] = useState<MergeMethodInfo[]>([]);
  const [selectedSubject, setSelectedSubject] = useState('');
  const [selectedMethod, setSelectedMethod] = useState('union_dedup');
  const [mergeResult, setMergeResult] = useState<MergeResult | null>(null);
  const [customTaskIds, setCustomTaskIds] = useState('');
  const [conflictChoice, setConflictChoice] = useState<Record<string, { subject: string; note: string }>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(() => {
    Promise.all([getEntities(), getMergeMethods()])
      .then(([ent, mRes]) => {
        setData(ent);
        const list = mRes.methods || [];
        setMethods(list);
        if (list.length) {
          setSelectedMethod((prev) => (list.some((m) => m.id === prev) ? prev : list[0].id));
        }
        if (ent.subjects?.length) {
          const s0 = ent.subjects[0] as { holder_masked?: string; key?: string; subject?: string };
          const firstKey = String(s0.holder_masked || s0.key || s0.subject || '');
          setSelectedSubject((prev) => prev || firstKey);
        }
      })
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function runSubjectMerge(subjectKey?: string) {
    const sub = subjectKey ?? selectedSubject;
    if (!sub) return;
    setSelectedSubject(sub);
    setBusy(true);
    setError('');
    try {
      const res = await getEntitiesMerge(sub, selectedMethod);
      setMergeResult(normalizeMergeResult(res, selectedMethod, sub));
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  async function runTaskIdMerge() {
    const ids = customTaskIds
      .split(/[,，\s]+/)
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n) && n > 0);
    if (!ids.length) {
      setError('请输入至少一个有效任务编号（用逗号分隔）。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const res = await mergeTasks(ids, selectedMethod);
      setMergeResult(normalizeMergeResult(res, selectedMethod, `任务 ${ids.join(', ')}`));
      setNotice(`已按「${selectedMethod}」口径合并任务 ${ids.join(', ')}。`);
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  async function handleResolve(c: ConflictItem) {
    if (!c.account_key) return;
    const choice = conflictChoice[c.account_key];
    const targetSubject = choice?.subject || c.holders?.[0] || '';
    if (!targetSubject) return;
    setBusy(true);
    setError('');
    try {
      await resolveEntityConflict({ account_key: c.account_key, subject: targetSubject, note: choice?.note || undefined });
      setNotice(`已签字确认账户 ${c.account_masked || c.account_key} 归属于「${targetSubject}」。`);
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  async function handleUndoConflict(accountKey: string) {
    setBusy(true);
    setError('');
    try {
      await undoEntityConflict(accountKey);
      setNotice('已撤销人工归属裁决。');
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  const conflicts = (data?.conflicts ?? []) as ConflictItem[];
  const subjects = (data?.subjects ?? []) as { holder_masked?: string; key?: string; subject?: string; accounts?: Record<string, number> | string[]; tasks?: number[] }[];

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>客户多账户合并与冲突裁决</h1>
          <p className="sub">同客户多张卡自动识别内部互转与期间重叠，支持多口径合并测算；同卡异名冲突需审贷人员签字裁决。</p>
        </div>
      </header>

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="ok">{notice}</Notice> : null}

      {data ? (
        <section className="score-row">
          <div className="score"><span className="score-value">{data.summary.accounts}</span><span className="muted small">已识别账户</span></div>
          <div className="score"><span className="score-value">{data.summary.subjects}</span><span className="muted small">客户主体</span></div>
          <div className="score"><span className="score-value">{data.summary.multi_account_subjects}</span><span className="muted small">多账户客户</span></div>
          <div className="score"><span className="score-value">{data.summary.conflicts}</span><span className="muted small">户名冲突数</span></div>
        </section>
      ) : null}

      <section className="merge-workbench">
        <h2>多账户合并分析工作台（{methods.length || 8} 种口径）</h2>
        <div className="filters-bar">
          <div className="filters">
            <select value={selectedSubject} onChange={(e) => setSelectedSubject(e.target.value)} aria-label="选择客户主体">
              <option value="">选择客户主体…</option>
              {subjects.map((s, idx) => {
                const key = String(s.holder_masked || s.key || s.subject || `主体#${idx + 1}`);
                const taskCount = s.tasks?.length ?? 0;
                return (
                  <option key={key} value={key}>
                    {key}（{taskCount} 份流水）
                  </option>
                );
              })}
            </select>
            <select value={selectedMethod} onChange={(e) => setSelectedMethod(e.target.value)} aria-label="选择合并口径">
              {methods.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label} · {m.short}
                </option>
              ))}
            </select>
            <Button size="sm" disabled={busy || !selectedSubject} onClick={() => void runSubjectMerge()}>
              {busy ? '计算中…' : '按主体合并'}
            </Button>
          </div>
          <div className="filters">
            <input
              type="text"
              placeholder="按任务ID合并，如 12,15"
              value={customTaskIds}
              onChange={(e) => setCustomTaskIds(e.target.value)}
            />
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => void runTaskIdMerge()}>
              指定任务合并
            </Button>
          </div>
        </div>

        {mergeResult && (
          <div className="merge-result-card">
            <div className="ann-preview-head">
              <strong>
                合并结果：{mergeResult.subject || '指定任务集'} · 口径「{mergeResult.method?.label || selectedMethod}」
              </strong>
              <span className="small muted">{mergeResult.method?.formula}</span>
            </div>
            {mergeResult.coverage && (
              <div className="ann-meta-chips" style={{ marginBottom: 10 }}>
                <span className="ann-meta-chip">原始笔数：<b>{mergeResult.coverage.raw_txn_count ?? '—'}</b></span>
                <span className="ann-meta-chip">合并净笔数：<b>{mergeResult.coverage.merged_txn_count ?? '—'}</b></span>
                <span className="ann-meta-chip">剔除重复/互转：<b>{(mergeResult.coverage.dropped_duplicates ?? 0) + (mergeResult.coverage.internal_transfers ?? 0)}</b></span>
                <span className="ann-meta-chip">覆盖月数：<b>{mergeResult.coverage.months ?? 0}</b></span>
              </div>
            )}
            {mergeResult.warnings?.length ? (
              <div className="ann-preview-notes">
                {mergeResult.warnings.map((w, i) => (
                  <span key={i} className="pill warn">{w}</span>
                ))}
              </div>
            ) : null}
            {mergeResult.metrics?.length ? (
              <table className="grid compact">
                <thead><tr><th>指标代号</th><th>指标名称</th><th>合并值</th><th>单位</th><th>说明</th></tr></thead>
                <tbody>
                  {mergeResult.metrics.map((m) => (
                    <tr key={m.code}>
                      <td className="mono small">{m.code}</td>
                      <td>{m.name}</td>
                      <td className="mono">{formatMetricValue(m.value)}</td>
                      <td className="small muted">{m.unit}</td>
                      <td className="small muted">{m.how || m.note || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            {mergeResult.accounts?.length ? (
              <div style={{ marginTop: 10 }}>
                <span className="small muted">纳入合并的账户明细（{mergeResult.accounts.length} 个）：</span>
                <table className="grid compact" style={{ marginTop: 4 }}>
                  <thead><tr><th>任务</th><th>银行 / 账号</th><th>月数</th><th>笔数</th><th>期末余额</th><th>结论</th></tr></thead>
                  <tbody>
                    {mergeResult.accounts.map((acc) => (
                      <tr key={acc.task_id}>
                        <td className="mono small">#{acc.task_id}</td>
                        <td>{acc.bank_name || '—'} · <span className="mono small">{acc.account_masked || '—'}</span></td>
                        <td>{acc.months ?? '—'}</td>
                        <td>{acc.txn_count ?? '—'}</td>
                        <td className="mono small">{acc.balance_end ?? '—'}</td>
                        <td className="small muted">{acc.verdict || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {mergeResult.unsupported?.length ? (
              <div style={{ marginTop: 10 }}>
                <span className="small muted">本口径下不适用/未计算指标：</span>
                <ul className="plain small muted">
                  {mergeResult.unsupported.map((u) => (
                    <li key={u.code}>{u.code} {u.name}：{u.reason}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        )}
      </section>

      {conflicts.length > 0 && (
        <section>
          <h2>账户归属冲突裁决（{conflicts.length}）</h2>
          <table className="grid compact">
            <thead>
              <tr><th>账户</th><th>涉及户名</th><th>涉及任务</th><th>状态</th><th>人工裁决</th></tr>
            </thead>
            <tbody>
              {conflicts.map((c, idx) => {
                const key = c.account_key || String(idx);
                const holders = c.holders || [];
                const val = conflictChoice[key] || { subject: c.resolution?.subject || holders[0] || '', note: '' };
                return (
                  <tr key={key}>
                    <td>
                      <strong>{c.bank_name || '银行'}</strong>
                      <div className="small muted mono">{c.account_masked || c.account_key}</div>
                    </td>
                    <td>{holders.join(' / ')}</td>
                    <td className="small muted">{(c.tasks || []).join(', ')}</td>
                    <td>
                      {c.resolved ? (
                        <span className="pill ok">已裁决：{c.resolution?.subject}</span>
                      ) : (
                        <span className="pill warn">待裁决</span>
                      )}
                    </td>
                    <td>
                      {c.resolved && c.account_key ? (
                        <button type="button" className="link-btn" onClick={() => void handleUndoConflict(c.account_key as string)}>
                          撤销裁决
                        </button>
                      ) : (
                        <div className="filters">
                          <select
                            value={val.subject}
                            onChange={(e) =>
                              setConflictChoice((prev) => ({
                                ...prev,
                                [key]: { ...val, subject: e.target.value },
                              }))
                            }
                          >
                            {holders.map((h) => (
                              <option key={h} value={h}>{h}</option>
                            ))}
                          </select>
                          <input
                            type="text"
                            placeholder="备注依据"
                            value={val.note}
                            onChange={(e) =>
                              setConflictChoice((prev) => ({
                                ...prev,
                                [key]: { ...val, note: e.target.value },
                              }))
                            }
                          />
                          <Button size="sm" disabled={busy} onClick={() => void handleResolve(c)}>
                            签字确认
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      <section>
        <h2>已识别账户清单</h2>
        <table className="grid compact">
          <thead>
            <tr><th>银行</th><th>账号（脱敏）</th><th>户名分布</th><th>涉及任务</th></tr>
          </thead>
          <tbody>
            {(data?.accounts ?? []).map((account) => (
              <tr key={account.key}>
                <td>{account.bank_name}</td>
                <td className="small muted mono">{account.account_masked}</td>
                <td>{Object.keys(account.holders ?? {}).join('、') || '—'}</td>
                <td className="small muted">{(account.tasks ?? []).slice(0, 8).join('、')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
