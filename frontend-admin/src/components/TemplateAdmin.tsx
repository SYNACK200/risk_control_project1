import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  deleteTemplate, disableTemplate, listTemplates, publishTemplate, templateStats,
  type TemplateRow, type TemplateStats,
} from '../lib/api';

/** 模板库：只看清单与状态，详情/试跑/编辑/框选都进详情页。 */
export function TemplateAdmin() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<TemplateRow[]>([]);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [stats, setStats] = useState<Record<number, TemplateStats>>({});
  const [openStat, setOpenStat] = useState<number | null>(null);

  async function refresh() {
    try {
      setRows(await listTemplates());
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

  /** 点一次展开使用情况，再点一次收起。 */
  async function toggleStats(id: number) {
    if (openStat === id) { setOpenStat(null); return; }
    setOpenStat(id);
    if (!stats[id]) {
      try {
        const s = await templateStats(id);
        setStats(prev => ({ ...prev, [id]: s }));
      } catch { /* ignore */ }
    }
  }

  return (
    <div className="result">
      <div className="result-head">
        <h2>模板库</h2>
        <span className="muted">{rows.length} 个版本 · {banks.length} 家银行 · 同一银行只允许一个启用版本</span>
      </div>
      {msg && <div className="notice ok">{msg}</div>}
      {error && <div className="notice error">{error}</div>}

      <section className="card">
        <div className="card-body">
          <table className="mini">
            <thead>
              <tr><th>ID</th><th>银行</th><th>版本</th><th>状态</th><th>使用</th><th>成功率</th><th>字段</th><th>操作</th></tr>
            </thead>
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
                      <button className="link-btn" type="button" onClick={() => { void toggleStats(t.id); }}>
                        {s ? s.tasks_total + ' 条' : '使用情况'}{openStat === t.id ? ' ▴' : ' ▾'}
                      </button>
                      {openStat === t.id && s && <span className="muted small"> 成功 {s.tasks_done} · 失败 {s.tasks_failed} · 平均 {s.avg_txn_count ?? '—'} 笔</span>}
                    </td>
                    <td className="num">{s?.success_rate === null || s?.success_rate === undefined ? '—' : Math.round(s.success_rate * 100) + '%'}</td>
                    <td className="muted small">{Object.keys(t.field_map ?? {}).length} 项</td>
                    <td className="row-actions">
                      <button className="link-btn" type="button" onClick={() => navigate('/templates/' + t.id)}>详情</button>
                      {t.status !== 'enabled' && <button className="link-btn" type="button" disabled={busy} onClick={() => { void act('已启用 #' + t.id, () => publishTemplate(t.id)); }}>启用</button>}
                      {t.status === 'enabled' && <button className="link-btn" type="button" disabled={busy} onClick={() => { void act('已停用 #' + t.id, () => disableTemplate(t.id)); }}>停用</button>}
                      <button className="link-btn danger-text" type="button" disabled={busy} onClick={() => {
                        if (!window.confirm('删除模板 #' + t.id + '？被任务引用时只会软删除。')) return;
                        void act('已删除 #' + t.id, () => deleteTemplate(t.id));
                      }}>删除</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && <p className="muted">还没有模板。去「新建模板」标注一份样例。</p>}
        </div>
      </section>

      <p className="muted small">看字段映射、框选回看、试跑验证、编辑新版本，点任意一行「详情」。</p>
    </div>
  );
}