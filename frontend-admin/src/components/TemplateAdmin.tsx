import { useEffect, useState } from 'react';
import { createTemplate, inferTemplate, listTemplates, publishTemplate, type InferResult, type TemplateRow } from '../lib/api';

export function TemplateAdmin() {
  const [rows, setRows] = useState<TemplateRow[]>([]);
  const [bank, setBank] = useState('ICBC');
  const [json, setJson] = useState('');
  const [msg, setMsg] = useState('');
  const [inferFile, setInferFile] = useState<File | null>(null);
  const [marks, setMarks] = useState('[{"field":"txn_date","page":0,"x":105,"y":60},{"field":"amount","page":0,"x":530,"y":60},{"field":"balance","page":0,"x":650,"y":60}]');
  const [pw, setPw] = useState('');
  const [infer, setInfer] = useState<InferResult | null>(null);

  async function refresh() {
    try { setRows(await listTemplates()); } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  }
  useEffect(() => { void refresh(); }, []);

  async function save() {
    setMsg('');
    try {
      const parsed = JSON.parse(json);
      const fieldMap = parsed.field_map ?? parsed;
      const { id } = await createTemplate({ bank_code: bank, field_map: fieldMap, header_columns: parsed.header_columns, version: parsed.version ?? 1 });
      setMsg(`已保存模板 #${id}（草稿），点“启用”后用于解析`);
      await refresh();
    } catch (e) {
      setMsg(e instanceof Error ? `保存失败：${e.message}` : String(e));
    }
  }

  async function runInfer() {
    if (!inferFile) { setMsg('请先选择一份样本文件'); return; }
    setMsg('正在外推…'); setInfer(null);
    try {
      const form = new FormData();
      form.append('file', inferFile);
      form.append('marks', marks);
      form.append('bank_code', bank);
      if (pw) form.append('password', pw);
      const res = await inferTemplate(form);
      setInfer(res);
      setMsg('外推完成：识别 ' + res.columns.length + ' 列，映射 ' + Object.keys(res.field_map).length + ' 个字段');
    } catch (e) {
      setMsg(e instanceof Error ? '外推失败：' + e.message : String(e));
    }
  }

  async function saveInfer() {
    if (!infer || infer.valid === false) return;
    try {
      const { id } = await createTemplate({ bank_code: infer.bank_code, field_map: infer.field_map, version: 1 });
      setMsg('已保存模板 #' + id + '（草稿），点“启用”后用于解析');
      await refresh();
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  }

  async function enable(id: number) {
    try { await publishTemplate(id); setMsg(`模板 #${id} 已启用`); await refresh(); }
    catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  }

  return (
    <div className="result-wrap">
      <div className="result">
        <div className="result-head"><h2>模板管理</h2></div>
        {msg && <div className="notice info">{msg}</div>}

        <table className="mini">
          <thead><tr><th>ID</th><th>银行</th><th>版本</th><th>状态</th><th></th></tr></thead>
          <tbody>
            {rows.map(t => (
              <tr key={t.id}>
                <td className="mono">{t.id}</td><td>{t.bank_code}</td><td>v{t.version}</td><td>{t.status}</td>
                <td>{t.status !== 'enabled' && <button className="btn" onClick={() => { void enable(t.id); }}>启用</button>}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="muted">还没有模板。</td></tr>}
          </tbody>
        </table>

        <h3>只标几处，让系统外推整张表</h3>
        <p className="muted">流程：选一份样本文件 → 点几个格子（或直接改下面的 marks）→ 外推 → 确认后保存草稿并启用。</p>
        <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
          <input type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={e => setInferFile(e.target.files?.[0] ?? null)} />
          <input type="password" placeholder="文件口令（如需）" value={pw} onChange={e => setPw(e.target.value)} />
          <button className="btn primary" onClick={() => { void runInfer(); }}>外推模板</button>
        </div>
        <textarea rows={3} style={{ width: '100%', fontFamily: 'ui-monospace, monospace', fontSize: 12, marginTop: 8 }}
          value={marks} onChange={e => setMarks(e.target.value)} />
        {infer && (
          <div style={{ marginTop: 12 }}>
            <p className="muted">识别到 {infer.columns.length} 列；映射：{Object.entries(infer.field_map).map(([k, v]) => k + '→' + v).join('，')}</p>
            <table className="mini">
              <thead><tr><th>字段</th><th>列</th><th>来源</th><th>置信</th><th>依据</th></tr></thead>
              <tbody>
                {infer.provenance.map(r => (
                  <tr key={r.field}><td>{r.field}</td><td>{r.column ?? '—'}</td><td>{r.source}</td>
                    <td>{r.confidence}</td><td className="muted">{r.why}</td></tr>
                ))}
              </tbody>
            </table>
            {infer.warnings.length > 0 && <p className="notice error">{infer.warnings.join('；')}</p>}
            {infer.valid !== false && <button className="btn" style={{ marginTop: 8 }} onClick={() => { void saveInfer(); }}>保存为草稿</button>}
          </div>
        )}

        <h3>新增模板</h3>
        <div className="row"><label>银行代码</label><input type="text" value={bank} onChange={e => setBank(e.target.value)} /></div>
        <p className="muted">粘贴 field_map JSON（来自标注页导出，或 ICBC/CMB 模板文件）</p>
        <textarea rows={10} style={{ width: '100%', fontFamily: 'ui-monospace, monospace', fontSize: 12 }} value={json} onChange={e => setJson(e.target.value)} placeholder='{"field_map":{"txn_date":0,"amount":8,"balance":9}}' />
        <div className="row" style={{ marginTop: 8 }}><button className="btn primary" onClick={() => { void save(); }}>保存为草稿</button></div>
      </div>
    </div>
  );
}

