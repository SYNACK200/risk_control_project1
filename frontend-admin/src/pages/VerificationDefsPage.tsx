import { useEffect, useState } from 'react';
import { getVerificationDefinitions } from '../lib/api';

type VDef = { code: string; name: string; category?: string; severity?: string; description?: string };

/** 校验项（只读）：报告里 36 个识别自检点的定义，说明每项查什么。 */
export function VerificationDefsPage() {
  const [items, setItems] = useState<VDef[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    getVerificationDefinitions()
      .then((d: unknown) => {
        const obj = d as { items?: VDef[] };
        setItems(obj.items ?? []);
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="result">
      <div className="result-head">
        <h2>校验项</h2>
        <span className="muted">{items.length} 项 · 报告「识别自检」用的定义 · 只读</span>
      </div>
      {error && <div className="notice error">{error}</div>}
      <section className="card">
        <div className="card-body">
          <table className="mini">
            <thead><tr><th>编码</th><th>名称</th><th>类别</th><th>严重度</th><th>说明</th></tr></thead>
            <tbody>
              {items.map(v => (
                <tr key={v.code}>
                  <td className="mono">{v.code}</td>
                  <td>{v.name}</td>
                  <td className="muted small">{v.category ?? '—'}</td>
                  <td className="muted small">{v.severity ?? '—'}</td>
                  <td className="muted small">{v.description ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.length === 0 && !error && <p className="muted">加载中…</p>}
        </div>
      </section>
    </div>
  );
}
