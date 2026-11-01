import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { TemplateLayoutView } from '../components/TemplateLayoutView';
import {
  disableTemplate, duplicateTemplate, listTemplates, previewTemplate, publishTemplate, templateStats, updateTemplate,
  type TemplatePreview, type TemplateRow, type TemplateStats,
} from '../lib/api';

const FIELD_HINTS = ['txn_date', 'summary', 'amount', 'income', 'expense', 'balance', 'counterparty', 'channel', 'account_no', 'currency'];

/** 模板详情：看字段、看框选、试跑、编辑一个新版本。列表页不再承载这些。 */
export function TemplateDetailPage() {
  const { id } = useParams();
  const templateId = Number(id);
  const navigate = useNavigate();

  const [row, setRow] = useState<TemplateRow | null>(null);
  const [stats, setStats] = useState<TemplateStats | null>(null);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editBank, setEditBank] = useState('');
  const [editJson, setEditJson] = useState('');
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewFile, setPreviewFile] = useState<File | null>(null);
  const [previewPw, setPreviewPw] = useState('');
  const [preview, setPreview] = useState<TemplatePreview | null>(null);

  async function load() {
    try {
      const list = await listTemplates();
      const found = list.find(t => t.id === templateId) ?? null;
      setRow(found);
      if (!found) setError('找不到这个模板（可能已被删除）');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [templateId]);

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(true); setMsg(''); setError('');
    try { await fn(); setMsg(label); await load(); if (stats) await loadStats(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function loadStats() {
    if (!row) return;
    try { setStats(await templateStats(row.id)); } catch { setStats(null); }
  }

  function openEdit() {
    if (!row) return;
    setEditOpen(true);
    setEditBank(row.bank_code);
    setEditJson(JSON.stringify(row.field_map ?? {}, null, 2));
  }

  async function saveEdit() {
    if (!row) return;
    let fm: Record<string, unknown>;
    try { fm = JSON.parse(editJson); } catch (e) { setError('JSON 不合法：' + (e instanceof Error ? e.message : String(e))); return; }
    await act('已保存为新版本草稿，确认无误后点启用', () => updateTemplate(row.id, { bank_code: editBank, field_map: fm }));
    setEditOpen(false);
  }

  async function runPreview() {
    if (!row || !previewFile) return;
    setBusy(true); setError(''); setPreview(null);
    try { setPreview(await previewTemplate(row.id, previewFile, previewPw || undefined)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

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

  const fieldCount = Object.keys(row.field_map ?? {}).length;
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
            <span>字段：{fieldCount} 项</span>
            <button className="link-btn" type="button" onClick={() => { void loadStats(); }}>查看使用情况</button>
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
            <button className="btn secondary" type="button" onClick={openEdit}>编辑字段映射</button>
            <button className="btn secondary" type="button" onClick={() => setPreviewOpen(v => !v)}>{previewOpen ? '收起试跑' : '试跑这个模板'}</button>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head-static">
          <strong>字段映射</strong>
          <span className="muted small">值可以是表头别名（如“交易日期”）或从 0 开始的列序号</span>
        </div>
        <div className="card-body">
          <table className="mini">
            <thead><tr><th>字段</th><th>映射到</th></tr></thead>
            <tbody>
              {Object.entries(row.field_map ?? {}).map(([field, target]) => (
                <tr key={field}>
                  <td className="mono">{field}</td>
                  <td>{typeof target === 'string' ? target : '第 ' + (Number(target) + 1) + ' 列'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="card-head-static">
          <strong>框选回看</strong>
          <span className="muted small">建模板时用的样本页，方框就是当时选中的列</span>
        </div>
        <div className="card-body"><TemplateLayoutView templateId={row.id} /></div>
      </section>

      {editOpen && (
        <section className="tpl-panel">
          <h3>编辑字段映射（保存生成 v{row.version + 1} 草稿）</h3>
          <div className="tpl-row">
            <label>银行代码</label>
            <input className="thr-input" value={editBank} onChange={e => setEditBank(e.target.value.toUpperCase())} />
          </div>
          <label className="muted small">键 = 字段名，值 = 列下标或表头别名：{FIELD_HINTS.join(' / ')}</label>
          <textarea className="tpl-json" rows={8} value={editJson} onChange={e => setEditJson(e.target.value)} />
          <div className="tpl-row">
            <button className="btn" type="button" disabled={busy} onClick={() => { void saveEdit(); }}>保存为新版本</button>
            <button className="link-btn" type="button" onClick={() => setEditOpen(false)}>取消</button>
          </div>
        </section>
      )}

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
                    {preview.rows.slice(0, 10).map((r, i) => (
                      <tr key={i}><td>{r.txn_date ?? '—'}</td><td>{r.direction ?? '—'}</td><td className="num">{r.amount ?? '—'}</td><td className="num">{r.balance ?? '—'}</td></tr>
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
