import { useEffect, useState } from 'react';
import { getMetricDefinitions, type MetricDef } from '../lib/api';

/** 指标口径（只读）：40 项指标的定义与公式，供业务核对口径，不在这里改值。 */
export function MetricDefsPage() {
  const [items, setItems] = useState<MetricDef[]>([]);
  const [version, setVersion] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [q, setQ] = useState('');

  useEffect(() => {
    getMetricDefinitions()
      .then(d => { setItems(d.items); setVersion(d.metric_set_version); })
      .catch(e => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const groups = Array.from(new Set(items.map(i => i.group)));
  const filtered = q.trim()
    ? items.filter(i => (i.code + i.name + i.group).toLowerCase().includes(q.trim().toLowerCase()))
    : items;

  return (
    <div className="result">
      <div className="result-head">
        <h2>指标口径</h2>
        <span className="muted">{items.length} 项指标 · 口径版本 v{version ?? '—'} · 只读</span>
      </div>
<div className="notice info" style={{ lineHeight: 1.8 }}>
        <b>这页解决什么问题：</b>报告里的数字被客户/评审质疑「这个 0.42 是怎么算的」时，在这里查到它的口径、公式和输入，
        不用去翻代码。<b>怎么用：</b>用下面的搜索框按指标名或编码定位；报告页点指标名也会跳到这里。
      </div>
      {error && <div className="notice error">{error}</div>}
      <section className="card">
        <div className="card-body">
          <input className="thr-input" placeholder="搜索指标名或编码" value={q} onChange={e => setQ(e.target.value)} style={{ marginBottom: 12 }} />
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
          <p className="muted small">分组：{groups.join(' / ') || '—'}</p>
        </div>
      </section>
    </div>
  );
}