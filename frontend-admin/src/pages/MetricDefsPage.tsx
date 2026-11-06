import { useEffect, useState } from 'react';
import {
  createCustomMetric, deleteCustomMetric, getMetricDefinitions, listCustomMetrics,
  type CustomMetric, type MetricDef,
} from '../lib/api';
import { useIsAdmin } from '../lib/auth';

/** 指标口径：内置 40 项（只读）+ 自定义指标（管理员可登记，实验性）。 */
export function MetricDefsPage() {
  const isAdmin = useIsAdmin();
  const [items, setItems] = useState<MetricDef[]>([]);
  const [version, setVersion] = useState<number | null>(null);
  const [custom, setCustom] = useState<CustomMetric[]>([]);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [q, setQ] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ code: '', name: '', unit: '', group_name: '', formula: '', inputs: '', note: '' });

  async function loadAll() {
    try {
      const [d, c] = await Promise.all([getMetricDefinitions(), listCustomMetrics()]);
      setItems(d.items);
      setVersion(d.metric_set_version);
      setCustom(c.items);
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => { void loadAll(); }, []);

  async function submit() {
    if (!form.code.trim() || !form.name.trim()) { setError('编码与名称必填'); return; }
    setBusy(true); setError(''); setMsg('');
    try {
      await createCustomMetric({
        code: form.code.trim(),
        name: form.name.trim(),
        unit: form.unit || undefined,
        group_name: form.group_name || undefined,
        formula: form.formula || undefined,
        inputs: form.inputs || undefined,
        note: form.note || undefined,
      });
      setMsg('已登记自定义指标 ' + form.code.trim().toUpperCase());
      setForm({ code: '', name: '', unit: '', group_name: '', formula: '', inputs: '', note: '' });
      setFormOpen(false);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(m: CustomMetric) {
    if (!window.confirm('删除自定义指标 ' + m.code + '？')) return;
    setBusy(true); setError('');
    try {
      await deleteCustomMetric(m.id);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const groups = Array.from(new Set(items.map(i => i.group)));
  const filtered = q.trim()
    ? items.filter(i => (i.code + i.name + i.group).toLowerCase().includes(q.trim().toLowerCase()))
    : items;

  return (
    <div className="result">
      <div className="result-head">
        <h2>指标口径</h2>
        <span className="muted">内置 {items.length} 项 · 自定义 {custom.length} 项 · 口径版本 v{version ?? '—'}</span>
      </div>

      <div className="notice info">
        报告里的数字被质疑时，在这里查口径、公式与输入。自定义指标仅登记口径，暂不参与计算。
      </div>

      {msg && <div className="notice ok">{msg}</div>}
      {error && <div className="notice error">{error}</div>}

      <section className="card">
        <div className="card-head-static">
          <strong>自定义指标（实验性）</strong>
          <span className="muted small">
            {isAdmin ? '管理员可登记与删除' : '仅管理员可登记；你可以查看口径'}
          </span>
        </div>
        <div className="card-body">
          {isAdmin && (
            <div className="tpl-row" style={{ marginBottom: 10 }}>
              <button className="btn" type="button" onClick={() => setFormOpen(v => !v)}>
                {formOpen ? '收起表单' : '+ 登记自定义指标'}
              </button>
            </div>
          )}
          {formOpen && isAdmin && (
            <div className="metric-form">
              <div className="tpl-row">
                <input className="thr-input" placeholder="编码，如 X01" value={form.code}
                  onChange={e => setForm({ ...form, code: e.target.value.toUpperCase() })} />
                <input className="thr-input" placeholder="名称，如 夜间小额高频占比" value={form.name}
                  onChange={e => setForm({ ...form, name: e.target.value })} />
                <input className="thr-input narrow" placeholder="单位" value={form.unit}
                  onChange={e => setForm({ ...form, unit: e.target.value })} />
                <input className="thr-input narrow" placeholder="分组" value={form.group_name}
                  onChange={e => setForm({ ...form, group_name: e.target.value })} />
              </div>
              <div className="tpl-row">
                <input className="thr-input" placeholder="公式/口径，如 夜间(22:00-6:00)小额笔数 ÷ 总笔数" value={form.formula}
                  onChange={e => setForm({ ...form, formula: e.target.value })} />
              </div>
              <div className="tpl-row">
                <input className="thr-input" placeholder="输入项（用到哪些字段/交易）" value={form.inputs}
                  onChange={e => setForm({ ...form, inputs: e.target.value })} />
                <input className="thr-input" placeholder="备注（为什么加这个维度）" value={form.note}
                  onChange={e => setForm({ ...form, note: e.target.value })} />
              </div>
              <button className="btn" type="button" disabled={busy} onClick={() => void submit()}>
                {busy ? '提交中…' : '登记'}
              </button>
            </div>
          )}

          {custom.length === 0 ? (
            <p className="muted">还没有自定义指标。{isAdmin ? '点上面的按钮登记一个试试。' : ''}</p>
          ) : (
            <table className="mini">
              <thead><tr><th>编码</th><th>名称</th><th>单位</th><th>口径/公式</th><th>备注</th><th>操作</th></tr></thead>
              <tbody>
                {custom.map(m => (
                  <tr key={m.id}>
                    <td className="mono">{m.code}</td>
                    <td>{m.name}</td>
                    <td className="muted small">{m.unit ?? '—'}</td>
                    <td className="muted small">{m.formula ?? '—'}</td>
                    <td className="muted small">{m.note ?? '—'}</td>
                    <td>
                      {isAdmin && (
                        <button className="link-btn danger-text" type="button" disabled={busy}
                          onClick={() => { void remove(m); }}>删除</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      <section className="card">
        <div className="card-head-static">
          <strong>内置指标</strong>
          <span className="muted small">分组：{groups.join(' / ') || '—'} · 只读</span>
        </div>
        <div className="card-body">
          <input className="thr-input" placeholder="搜索指标名或编码" value={q}
            onChange={e => setQ(e.target.value)} style={{ marginBottom: 12 }} />
          <table className="mini">
            <thead><tr><th>编码</th><th>名称</th><th>分组</th><th>单位</th><th>公式</th><th>输入</th></tr></thead>
            <tbody>
              {filtered.map(m => (
                <tr key={m.code}>
                  <td className="mono">{m.code}</td>
                  <td>{m.name}</td>
                  <td className="muted small">{m.group}</td>
                  <td className="muted small">{m.unit}</td>
                  <td className="mono small">{m.formula}</td>
                  <td className="muted small">{m.inputs}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}