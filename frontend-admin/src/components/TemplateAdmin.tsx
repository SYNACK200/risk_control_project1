import { useEffect, useMemo, useState } from 'react';
import {
  createTemplate, deleteTemplate, disableTemplate, downloadAttachment, duplicateTemplate,
  importTemplate, inferTemplate, listTemplates, previewTemplate, publishTemplate, templateStats,
  updateTemplate,
  type InferResult, type TemplatePreview, type TemplateRow, type TemplateStats,
} from '../lib/api';

const FIELDS = ['txn_date', 'summary', 'amount', 'income', 'expense', 'balance', 'counterparty', 'channel', 'account_no', 'currency'];

export function TemplateAdmin() {
  const [rows, setRows] = useState<TemplateRow[]>([]);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [newBank, setNewBank] = useState('CMB');
  const [newJson, setNewJson] = useState('{\n  "txn_date": 0,\n  "summary": 2,\n  "amount": 4,\n  "balance": 6\n}');
  const [editing, setEditing] = useState<TemplateRow | null>(null);
  const [editBank, setEditBank] = useState('');
  const [editJson, setEditJson] = useState('');
  const [stats, setStats] = useState<Record<number, TemplateStats>>({});
  const [previewTarget, setPreviewTarget] = useState<TemplateRow | null>(null);
  const [previewFile, setPreviewFile] = useState<File | null>(null);
  const [previewPw, setPreviewPw] = useState('');
  const [preview, setPreview] = useState<TemplatePreview | null>(null);
  const [importJson, setImportJson] = useState('');
  const [inferFile, setInferFile] = useState<File | null>(null);
  const [marks, setMarks] = useState('[{"field":"txn_date","page":0,"x":105,"y":60}]');
  const [infer, setInfer] = useState<InferResult | null>(null);

  async function refresh() {
    try {
      const list = await listTemplates();
      setRows(list);
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => { void refresh(); }, []);
  const banks = useMemo(() => Array.from(new Set(rows.map(r => r.bank_code))).sort(), [rows]);

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(true); setMsg(''); setError('');
    try {
      await fn();
      setMsg(label);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function loadStats(id: number) {
    try {
      const s = await templateStats(id);
      setStats(prev => ({ ...prev, [id]: s }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function startEdit(row: TemplateRow) {
    setEditing(row);
    setEditBank(row.bank_code);
    setEditJson(JSON.stringify(row.field_map ?? {}, null, 2));
    setMsg('正在编辑 #' + row.id + '，保存会生成新版本（旧版本保留）');
  }

  async function saveEdit() {
    if (!editing) return;
    let fieldMap: Record<string, unknown>;
    try {
      fieldMap = JSON.parse(editJson);
    } catch (e) {
      setError('JSON 不合法：' + (e instanceof Error ? e.message : String(e)));
      return;
    }
    if (!fieldMap || typeof fieldMap !== 'object' || Object.keys(fieldMap).length === 0) {
      setError('字段映射不能为空');
      return;
    }
    await act('已保存为新版本（草稿），需要时点启用', () => updateTemplate(editing.id, { bank_code: editBank, field_map: fieldMap }));
    setEditing(null);
  }

  async function runPreview() {
    if (!previewTarget || !previewFile) { setError('请选择模板与样例文件'); return; }
    setBusy(true); setError(''); setPreview(null);
    try {
      const res = await previewTemplate(previewTarget.id, previewFile, previewPw || undefined);
      setPreview(res);
      setMsg('试跑完成：' + res.txn_count + ' 笔 / ' + res.page_count + ' 页');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="result-wrap">
      <div className="result">
        <div className="result-head">
          <h2>模板管理</h2>
          <span className="muted">{rows.length} 个版本 · {banks.length} 家银行 · 同一银行只允许一个启用版本</span>
        </div>
        {msg && <div className="notice ok">{msg}</div>}
        {error && <div className="notice error">{error}</div>}

        <table className="mini">
          <thead><tr><th>ID</th><th>银行</th><th>版本</th><th>状态</th><th>使用</th><th>成功率</th><th>字段</th><th>操作</th></tr></thead>
          <tbody>
            {rows.map(t => {
              const s = stats[t.id];
              return (
                <tr key={t.id}>
                  <td className="mono">{t.id}</td>
                  <td>{t.bank_code}</td>
                  <td>v{t.version}</td>
                  <td><span className={'tag ' + (t.status === 'enabled' ? 'pass' : t.status === 'draft' ? 'limited' : '')}>{t.status}</span></td>
                  <td>
                    <button className="link-btn" type="button" onClick={() => { void loadStats(t.id); }}>{s ? s.tasks_total + ' 条' : '查看'}</button>
                    {s && <span className="muted small"> 成功 {s.tasks_done} · 失败 {s.tasks_failed} · 平均 {s.avg_txn_count ?? '—'} 笔</span>}
                  </td>
                  <td className="num">{s?.success_rate === null || s?.success_rate === undefined ? '—' : Math.round(s.success_rate * 100) + '%'}</td>
                  <td className="muted small">{Object.keys(t.field_map ?? {}).length} 项</td>
                  <td className="row-actions">
                    {t.status !== 'enabled' && <button className="link-btn" type="button" disabled={busy} onClick={() => { void act('已启用 #' + t.id, () => publishTemplate(t.id)); }}>启用</button>}
                    {t.status === 'enabled' && <button className="link-btn" type="button" disabled={busy} onClick={() => { void act('已停用 #' + t.id, () => disableTemplate(t.id)); }}>停用</button>}
                    <button className="link-btn" type="button" onClick={() => startEdit(t)}>编辑</button>
                    <button className="link-btn" type="button" disabled={busy} onClick={() => { void act('已复制为新草稿', () => duplicateTemplate(t.id)); }}>复制</button>
                    <button className="link-btn" type="button" onClick={() => { setPreviewTarget(t); setPreview(null); setMsg('试跑目标：#' + t.id + ' ' + t.bank_code + ' v' + t.version); }}>试跑</button>
                    <button className="link-btn" type="button" onClick={() => { void downloadAttachment('/templates/' + t.id + '/export', 'template-' + t.bank_code + '-v' + t.version + '.json').catch(e => setError(String(e))); }}>导出</button>
                    <button className="link-btn danger-text" type="button" disabled={busy} onClick={() => { void act('已删除 #' + t.id, () => deleteTemplate(t.id)); }}>删除</button>
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && <tr><td colSpan={8} className="muted">还没有模板：可以新建，或用下面的标注外推。</td></tr>}
          </tbody>
        </table>

        {editing && (
          <section className="tpl-panel">
            <h3>编辑模板 #{editing.id}（保存生成 v{editing.version + 1} 草稿）</h3>
            <div className="tpl-row">
              <label>银行代码</label>
              <input className="thr-input" value={editBank} onChange={e => setEditBank(e.target.value.toUpperCase())} />
            </div>
            <label className="muted small">字段映射（键 = 字段名，值 = 列下标，从 0 开始）：{FIELDS.join(' / ')}</label>
            <textarea className="tpl-json" rows={8} value={editJson} onChange={e => setEditJson(e.target.value)} />
            <div className="tpl-row">
              <button className="btn" type="button" disabled={busy} onClick={() => { void saveEdit(); }}>保存为新版本</button>
              <button className="link-btn" type="button" onClick={() => setEditing(null)}>取消</button>
            </div>
          </section>
        )}

        {previewTarget && (
          <section className="tpl-panel">
            <h3>试跑模板 #{previewTarget.id}（{previewTarget.bank_code} v{previewTarget.version}）</h3>
            <p className="muted">上传一份样例流水，用该模板解析，不写入数据库；用来验证列映射对不对。</p>
            <div className="tpl-row">
              <input type="file" accept=".pdf" onChange={e => setPreviewFile(e.target.files?.[0] ?? null)} />
              <input className="thr-input" type="password" placeholder="打开口令（可选）" value={previewPw} onChange={e => setPreviewPw(e.target.value)} />
              <button className="btn" type="button" disabled={busy || !previewFile} onClick={() => { void runPreview(); }}>开始试跑</button>
              <button className="link-btn" type="button" onClick={() => { setPreviewTarget(null); setPreview(null); }}>关闭</button>
            </div>
            {preview && (
              <div>
                <p className="muted">解析出 <b>{preview.txn_count}</b> 笔 / {preview.page_count} 页</p>
                {preview.warnings.length > 0 && <ul className="muted small">{preview.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
                {preview.rows.length > 0 && (
                  <table className="mini">
                    <thead><tr><th>日期</th><th>摘要</th><th>方向</th><th>金额</th><th>余额</th><th>页</th></tr></thead>
                    <tbody>
                      {preview.rows.map((r, i) => (
                        <tr key={i}>
                          <td className="mono">{r.txn_date ?? '—'}</td>
                          <td>{r.summary ?? '—'}</td>
                          <td>{r.direction === 'in' ? '收入' : r.direction === 'out' ? '支出' : '—'}</td>
                          <td className="num">{r.amount ?? '—'}</td>
                          <td className="num">{r.balance ?? '—'}</td>
                          <td className="num">{r.page_no}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </section>
        )}

        <section className="tpl-panel">
          <h3>新建模板 / 导入 JSON</h3>
          <div className="tpl-row">
            <label>银行代码</label>
            <input className="thr-input" value={newBank} onChange={e => setNewBank(e.target.value.toUpperCase())} />
            <button className="btn" type="button" disabled={busy} onClick={() => {
              let fm: Record<string, unknown>;
              try { fm = JSON.parse(newJson); } catch (e) { setError('JSON 不合法：' + (e instanceof Error ? e.message : String(e))); return; }
              void act('已新建草稿模板', () => createTemplate({ bank_code: newBank, field_map: fm }));
            }}>新建草稿</button>
          </div>
          <textarea className="tpl-json" rows={6} value={newJson} onChange={e => setNewJson(e.target.value)} />
          <div className="tpl-row">
            <textarea className="tpl-json" rows={4} placeholder="或粘贴导出的模板 JSON" value={importJson} onChange={e => setImportJson(e.target.value)} />
            <button className="btn secondary" type="button" disabled={busy || !importJson.trim()} onClick={() => {
              let payload: { bank_code: string; field_map: Record<string, unknown>; header_columns?: unknown[] };
              try { payload = JSON.parse(importJson); } catch (e) { setError('JSON 不合法：' + (e instanceof Error ? e.message : String(e))); return; }
              void act('已导入为新草稿', () => importTemplate(payload));
            }}>导入</button>
          </div>
        </section>

        <details className="tpl-panel">
          <summary>只标几处，让系统外推整张表（原有能力）</summary>
          <div className="tpl-row">
            <input type="file" accept=".pdf" onChange={e => setInferFile(e.target.files?.[0] ?? null)} />
            <input className="thr-input" value={marks} onChange={e => setMarks(e.target.value)} style={{ minWidth: 320 }} />
            <button className="btn secondary" type="button" disabled={busy || !inferFile} onClick={() => {
              if (!inferFile) return;
              const form = new FormData();
              form.append('file', inferFile);
              form.append('marks', marks);
              form.append('bank_code', newBank);
              setBusy(true); setError('');
              inferTemplate(form)
                .then(r => { setInfer(r); setMsg('外推完成：' + r.columns.length + ' 列，映射 ' + Object.keys(r.field_map).length + ' 个字段'); })
                .catch(e => setError(e instanceof Error ? e.message : String(e)))
                .finally(() => setBusy(false));
            }}>外推</button>
          </div>
          {infer && (
            <div>
              <p className="muted">银行 {infer.bank_code} · {infer.columns.length} 列 · 映射 {Object.keys(infer.field_map).length} 个字段</p>
              <pre className="tpl-pre">{JSON.stringify(infer.field_map, null, 2)}</pre>
              <button className="btn" type="button" onClick={() => { void act('已保存外推结果', () => createTemplate({ bank_code: infer.bank_code, field_map: infer.field_map })); }}>保存为草稿</button>
            </div>
          )}
        </details>
      </div>
    </div>
  );
}
