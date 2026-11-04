import { useEffect, useState } from 'react';
import { getVerificationDefinitions } from '../lib/api';

type VDef = { code: string; layer?: string; method?: string; name?: string };

const LAYER_LABEL: Record<string, string> = {
  file: '文件层', content: '内容层', ledger: '账实层', external: '外部层',
};

/** 校验项（只读）：报告「识别自检」里每个检查点查什么。 */
export function VerificationDefsPage() {
  const [items, setItems] = useState<VDef[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');

  useEffect(() => {
    setLoading(true);
    getVerificationDefinitions()
      .then((d: unknown) => {
        const list = Array.isArray(d) ? (d as VDef[]) : ((d as { items?: VDef[] })?.items ?? []);
        setItems(list);
        setError('');
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  const filtered = q.trim()
    ? items.filter(v => ((v.code || '') + (v.method || '') + (v.name || '')).toLowerCase().includes(q.trim().toLowerCase()))
    : items;
  const layers = Array.from(new Set(items.map(v => v.layer || '其他')));

  return (
    <div className="result">
      <div className="result-head">
        <h2>校验项</h2>
        <span className="muted">{items.length} 项 · 报告「识别自检」的检查点定义 · 只读</span>
      </div>

      <div className="notice info" style={{ lineHeight: 1.8 }}>
        <b>这页解决什么问题：</b>报告里写「识别自检 C3 笔数：无页脚笔数」这类提示时，业务看不懂编码含义，
        在这里查每一项到底查什么、属于哪一层。<b>怎么用：</b>按编码（F1/C3/L2…）搜索，回报告看该项状态。
      </div>

      {error && <div className="notice error">{error}</div>}

      <section className="card">
        <div className="card-body">
          <div className="tpl-row">
            <input className="thr-input" placeholder="搜索编码或检查内容（如 C3、页脚、余额链）"
              value={q} onChange={e => setQ(e.target.value)} />
            <span className="muted small">层：{layers.map(l => LAYER_LABEL[l] ?? l).join(' / ') || '—'}</span>
          </div>
          <table className="mini">
            <thead><tr><th style={{ width: 64 }}>编码</th><th style={{ width: 90 }}>所在层</th><th>检查什么</th></tr></thead>
            <tbody>
              {filtered.map(v => (
                <tr key={v.code}>
                  <td className="mono">{v.code}</td>
                  <td className="muted small">{LAYER_LABEL[v.layer ?? ''] ?? v.layer ?? '—'}</td>
                  <td>{v.method ?? v.name ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {loading && items.length === 0 && <p className="muted">加载中…</p>}
          {!loading && items.length === 0 && !error && (
            <p className="muted">后端没有返回校验项定义（/verification-definitions 为空）。</p>
          )}
          {!loading && items.length > 0 && filtered.length === 0 && <p className="muted">没有匹配的项。</p>}
        </div>
      </section>
    </div>
  );
}
