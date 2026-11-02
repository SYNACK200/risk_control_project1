import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { importTemplate } from '../lib/api';

/** 导入模板：把别处导出的模板 JSON（含 field_map）导入为草稿，再回模板库启用。 */
export function ImportTemplatePage() {
  const navigate = useNavigate();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');

  async function run() {
    const raw = text.trim();
    if (!raw) { setError('请先粘贴模板 JSON'); return; }
    let payload: { bank_code?: string; field_map?: Record<string, unknown>; header_columns?: unknown[] };
    try {
      payload = JSON.parse(raw);
    } catch (e) {
      setError('JSON 不合法：' + (e instanceof Error ? e.message : String(e)));
      return;
    }
    if (!payload.field_map || typeof payload.field_map !== 'object') { setError('JSON 里缺少 field_map'); return; }
    setBusy(true); setError(''); setMsg('');
    try {
      const created = await importTemplate({
        bank_code: (payload.bank_code || 'UNKNOWN').toUpperCase(),
        field_map: payload.field_map,
        header_columns: payload.header_columns,
      });
      setMsg('已导入为草稿模板 #' + created.id + '，去模板库启用');
      setText('');
    } catch (e) {
      setError('导入失败：' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="result">
      <div className="result-head">
        <h2>导入模板</h2>
        <span className="muted">从别处导出的 JSON 直接导入为草稿</span>
      </div>
      {msg && <div className="notice ok">{msg} <button className="pill-btn" type="button" onClick={() => navigate('/templates')}>去模板库</button></div>}
      {error && <div className="notice error">{error}</div>}
      <section className="card">
        <div className="card-body">
          <textarea className="tpl-json" rows={12} value={text} onChange={e => setText(e.target.value)}
            placeholder={'{\n  "bank_code": "CMB",\n  "field_map": { "txn_date": "交易日期", "amount": 4 }\n}'} />
          <button className="btn" type="button" disabled={busy} onClick={() => void run()}>
            {busy ? '导入中…' : '导入为草稿'}
          </button>
        </div>
      </section>
    </div>
  );
}
