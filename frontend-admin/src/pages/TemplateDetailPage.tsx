import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { TemplateLayoutView } from '../components/TemplateLayoutView';
import {
  disableTemplate, duplicateTemplate, getTemplateLayout, listTemplates, previewTemplate,
  publishTemplate, templateStats, updateTemplate,
  type TemplatePreview, type TemplateRow, type TemplateStats,
} from '../lib/api';
import { FIELD_DICT } from '../lib/fields';

/** 模板详情：字段映射用下拉选择（不用写 JSON）、框选回看、试跑、编辑新版本。 */
export function TemplateDetailPage() {
  const { id } = useParams();
  const templateId = Number(id);
  const navigate = useNavigate();

  const [row, setRow] = useState<TemplateRow | null>(null);
  const [stats, setStats] = useState<TemplateStats | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  // 字段映射编辑：{ 字段code -> '第N列' | 表头名 }
  const [editOpen, setEditOpen] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [editBank, setEditBank] = useState('');

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewFile, setPreviewFile] = useState<File | null>(null);
  const [previewPw, setPreviewPw] = useState('');
  const [preview, setPreview] = useState<TemplatePreview | null>(null);

  async function load() {
    try {
      const list = await listTemplates();
      const found = list.find(t => t.id === templateId) ?? null;
      setRow(found);
      if (!found) { setError('找不到这个模板（可能已被删除）'); return; }
      try {
        const lay = await getTemplateLayout(found.id);
        const hc = (lay as unknown as { header_columns?: (string | null)[] }).header_columns ?? [];
        setHeaders(hc.map((h, i) => (h && String(h).trim()) ? String(h) : '第 ' + (i + 1) + ' 列'));
      } catch { setHeaders([]); }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [templateId]);

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(true); setMsg(''); setError('');
    try { await fn(); setMsg(label); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function loadStats() {
    if (!row) return;
    try { setStats(await templateStats(row.id)); } catch { setStats(null); }
  }

  /** 把后端 field_map（{字段: 列号|别名}）转成下拉可用的字符串值。 */
  function toDraft(map: Record<string, unknown>): Record<string, string> {
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(map ?? {})) {
      if (typeof v === 'number') out[k] = String(v);
      else out[k] = String(v ?? '');
    }
    return out;
  }

  function openEdit() {
    if (!row) return;
    setEditOpen(true);
    setEditBank(row.bank_code);
    setDraft(toDraft(row.field_map ?? {}));
  }

  function columnOptions(): { value: string; label: string }[] {
    if (headers.length > 0) {
      return headers.map((h, i) => ({ value: String(i), label: h }));
    }
    return Array.from({ length: 20 }, (_, i) => ({ value: String(i), label: '第 ' + (i + 1) + ' 列' }));
  }

  async function saveEdit() {
    if (!row) return;
    const fieldMap: Record<string, unknown> = {};
    for (const [field, value] of Object.entries(draft)) {
      if (!value) continue;
      const asNum = Number(value);
      fieldMap[field] = Number.isFinite(asNum) && /^\d+$/.test(value) ? asNum : value;
    }
    if (Object.keys(fieldMap).length === 0) { setError('至少保留一个字段映射'); return; }
    await act('已保存为新版本草稿，确认无误后点启用', () => updateTemplate(row.id, { bank_code: editBank, field_map: fieldMap }));
    setEditOpen(false);
  }

  async function runPreview() {
    if (!row || !previewFile) return;
    setBusy(true); setError(''); setPreview(null);
    try { setPreview(await previewTemplate(row.id, previewFile, previewPw || undefined)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  const mapped = useMemo(() => Object.entries(row?.field_map ?? {}), [row]);
  const allFields = useMemo(() => {
    const known = FIELD_DICT.filter(f => f.scope !== 'meta').map(f => ({ code: f.code, label: f.label }));
    const extras = Object.keys(row?.field_map ?? {}).filter(k => !known.some(x => x.code === k)).map(k => ({ code: k, label: k }));
    return [...known, ...extras];
  }, [row]);

  if (!row) {
    return (
      <div className="result">
        <div className="result-head">
          <h2>模板详情</h2>
          <button className="pill-btn" type="button" onClick={() => navigate('/templates')}>返回模板库</button>
        </div>
        {error ? <div className="notice error">{error}</div> : <p className="muted">加载中…</p>}
      </div>
    );
  }

  return (
    <div className="result">
      <div className="result-head">
        <h2>模板 #{row.id} · {row.bank_code} v{row.version}</h2>
        <button className="pill-btn" type="button" onClick={() => navigate('/templates')}>返回模板库</button>
      </div>
      {msg && <div className="notice ok">{msg}</div>}
      {error && <div className="notice error">{error}</div>}

      <section className="card">
        <div className="card-body">
          <div className="tpl-row">
            <span>银行：<b>{row.bank_code}</b></span>
            <span>版本：v{row.version}</span>
            <span>状态：<span className={'tag ' + (row.status === 'enabled' ? 'pass' : row.status === 'draft' ? 'limited' : '')}>{row.status}</span></span>
            <span>字段：{mapped.length} 项</span>
            <button className="link-btn" type="button" onClick={() => { void loadStats(); }}>使用情况</button>
          </div>
          {stats && (
            <p className="muted small">
              任务 {stats.tasks_total} 条 · 成功 {stats.tasks_done} · 失败 {stats.tasks_failed} ·
              成功率 {stats.success_rate === null || stats.success_rate === undefined ? '—' : Math.round(stats.success_rate * 100) + '%'} ·
              平均 {stats.avg_txn_count ?? '—'} 笔
            </p>
          )}
          <div className="tpl-row">
            {row.status !== 'enabled' && <button className="btn" type="button" disabled={busy} onClick={() => { void act('已启用', () => publishTemplate(row.id)); }}>启用此版本</button>}
            {row.status === 'enabled' && <button className="btn secondary" type="button" disabled={busy} onClick={() => { void act('已停用', () => disableTemplate(row.id)); }}>停用</button>}
            <button className="btn secondary" type="button" disabled={busy} onClick={() => { void act('已复制为新草稿', () => duplicateTemplate(row.id)); }}>复制为新草稿</button>
            <button className="btn secondary" type="button" onClick={openEdit}>改字段映射</button>
            <button className="btn secondary" type="button" onClick={() => setPreviewOpen(v => !v)}>{previewOpen ? '收起试跑' : '试跑这个模板'}</button>
          </div>
        </div>
      </section>

      {!editOpen && (
      <section className="card">
        <div className="card-head-static">
          <strong>字段映射</strong>
          <span className="muted small">点「改字段映射」用下拉调整，不需要写 JSON</span>
        </div>
        <div className="card-body">
          <table className="mini">
            <thead><tr><th>字段</th><th>映射到</th></tr></thead>
            <tbody>
              {mapped.map(([field, target]) => (
                <tr key={field}>
                  <td className="mono">{field}</td>
                  <td>
                    {typeof target === 'number'
                      ? (headers[target] ?? '第 ' + (target + 1) + ' 列')
                      : String(target)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {mapped.length === 0 && <p className="muted">这个模板还没有字段映射。</p>}
        </div>
      </section>
      )}

      {editOpen && (
        <section className="tpl-panel">
          <h3>改字段映射（保存后生成 v{row.version + 1} 草稿）</h3>
          <p className="muted small">左边是字段，右边从下拉里选它对应哪一列。改完点保存即可。</p>
          <div className="tpl-row">
            <label>银行代码</label>
            <input className="thr-input" value={editBank} onChange={e => setEditBank(e.target.value.toUpperCase())} />
          </div>
          <table className="mini">
            <thead><tr><th style={{ width: 200 }}>字段</th><th>对应列</th><th style={{ width: 70 }}></th></tr></thead>
            <tbody>
              {Object.entries(draft).map(([field, value]) => (
                <tr key={field}>
                  <td className="mono">{field}</td>
                  <td>
                    <select value={value} onChange={e => setDraft({ ...draft, [field]: e.target.value })}>
                      <option value="">（不映射）</option>
                      {columnOptions().map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  </td>
                  <td>
                    <button className="link-btn danger-text" type="button"
                      onClick={() => { const next = { ...draft }; delete next[field]; setDraft(next); }}>移除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="tpl-row">
            <select value="" onChange={e => { if (e.target.value) setDraft({ ...draft, [e.target.value]: '' }); }}>
              <option value="">＋ 添加字段…</option>
              {allFields.filter(f => !(f.code in draft)).map(f => (
                <option key={f.code} value={f.code}>{f.label}（{f.code}）</option>
              ))}
            </select>
            <button className="btn" type="button" disabled={busy} onClick={() => { void saveEdit(); }}>保存为新版本</button>
            <button className="link-btn" type="button" onClick={() => setEditOpen(false)}>取消</button>
          </div>
        </section>
      )}

      <section className="card">
        <div className="card-head-static">
          <strong>框选回看</strong>
          <span className="muted small">建模板时用的样本页，方框就是当时选中的列</span>
        </div>
        <div className="card-body"><TemplateLayoutView templateId={row.id} /></div>
      </section>

      {previewOpen && (
        <section className="tpl-panel">
          <h3>试跑（不写入数据库）</h3>
          <p className="muted">上传一份样例流水，用这个模板解析，用来验证列映射对不对。</p>
          <div className="tpl-row">
            <input type="file" accept=".pdf" onChange={e => setPreviewFile(e.target.files?.[0] ?? null)} />
            <input className="thr-input" type="password" placeholder="打开口令（可选）" value={previewPw} onChange={e => setPreviewPw(e.target.value)} />
            <button className="btn" type="button" disabled={busy || !previewFile} onClick={() => { void runPreview(); }}>开始试跑</button>
          </div>
          {preview && (
            <div>
              <p className="muted">解析出 <b>{preview.txn_count}</b> 笔 / {preview.page_count} 页</p>
              {preview.warnings.length > 0 && <ul className="muted small">{preview.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
              {preview.rows.length > 0 && (
                <table className="mini">
                  <thead><tr><th>日期</th><th>方向</th><th>金额</th><th>余额</th></tr></thead>
                  <tbody>
                    {preview.rows.slice(0, 10).map((r2, i) => (
                      <tr key={i}><td>{r2.txn_date ?? '—'}</td><td>{r2.direction ?? '—'}</td><td className="num">{r2.amount ?? '—'}</td><td className="num">{r2.balance ?? '—'}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}