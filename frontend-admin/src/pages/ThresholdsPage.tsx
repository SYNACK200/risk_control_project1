import { useEffect, useMemo, useState } from 'react';
import { getThresholds, resetThresholds, saveThresholds, type ThresholdDef, type ThresholdPayload } from '../lib/api';

function asText(v: string | number | null): string {
  return v === null || v === undefined ? '' : String(v);
}

export function ThresholdsPage() {
  const [data, setData] = useState<ThresholdPayload | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [ok, setOk] = useState('');
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const payload = await getThresholds();
      setData(payload);
      setDraft(Object.fromEntries(Object.entries(payload.values).map(([k, v]) => [k, asText(v)])));
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => { void load(); }, []);

  const groups = useMemo(() => {
    const map = new Map<string, ThresholdDef[]>();
    for (const def of data?.defs ?? []) {
      const list = map.get(def.group) ?? [];
      list.push(def);
      map.set(def.group, list);
    }
    return Array.from(map.entries());
  }, [data]);

  const dirty = useMemo(() => {
    if (!data) return 0;
    return (data.defs ?? []).filter(def => {
      const now = draft[def.key] ?? '';
      return now.trim() !== asText(data.values[def.key]).trim();
    }).length;
  }, [data, draft]);

  async function onSave() {
    if (!data) return;
    setError('');
    setOk('');
    for (const def of data.defs) {
      const raw = (draft[def.key] ?? '').trim();
      if (raw === '') {
        if (def.key === 'counterparty_hhi') continue;
        setError(def.label + ' 不能为空');
        return;
      }
      const num = Number(raw);
      if (Number.isNaN(num)) {
        setError(def.label + ' 必须是数字');
        return;
      }
      if (def.minimum !== null && num < Number(def.minimum)) {
        setError(def.label + ' 不能小于 ' + def.minimum);
        return;
      }
      if (def.maximum !== null && num > Number(def.maximum)) {
        setError(def.label + ' 不能大于 ' + def.maximum);
        return;
      }
    }
    setBusy(true);
    try {
      const values: Record<string, string | null> = {};
      for (const def of data.defs) {
        const raw = (draft[def.key] ?? '').trim();
        values[def.key] = raw === '' ? null : raw;
      }
      const res = await saveThresholds(values, note || '银行侧调整');
      setOk('已保存为 v' + res.version + '，之后的受理与重解析按新参数计算');
      setNote('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onReset() {
    if (!window.confirm('恢复算法默认值会生成一个新版本，旧版本仍保留。继续？')) return;
    setBusy(true);
    setError('');
    try {
      await resetThresholds();
      setOk('已恢复默认参数');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return (
      <div className="result-wrap"><div className="result">
        <h2>风控参数</h2>
        {error ? <div className="notice error">{error}</div> : <p className="muted">加载中…</p>}
      </div></div>
    );
  }

  return (
    <div className="result-wrap">
      <div className="result">
        <div className="result-head">
          <h2>风控参数（超参）</h2>
          <span className="muted">当前生效 v{data.version} · 算法默认 v2 · {data.defs.length} 个参数</span>
        </div>
        <p className="muted">
          这里改的是判定阈值，不是指标口径。只影响<b>新受理</b>与<b>重解析</b>；已生成的报告保留当时的版本，不重写。
          改完会生成新版本并写审计。
        </p>

        {error && <div className="notice error">{error}</div>}
        {ok && <div className="notice ok">{ok}</div>}

        {groups.map(([group, defs]) => (
          <section key={group} className="thr-group">
            <h3>{group}</h3>
            <table className="mini thr-table">
              <thead>
                <tr><th>参数</th><th>当前值</th><th>单位</th><th>默认</th><th>范围</th><th>说明</th></tr>
              </thead>
              <tbody>
                {defs.map(def => {
                  const changed = (draft[def.key] ?? '').trim() !== asText(data.values[def.key]).trim();
                  return (
                    <tr key={def.key} className={changed ? 'thr-changed' : ''}>
                      <td>
                        {def.label}
                        <span className="muted small"> {def.key}</span>
                        {!def.calibrated && <span className="tag limited small" style={{ marginLeft: 6 }}>未校准</span>}
                      </td>
                      <td>
                        <input
                          className="thr-input"
                          type="number"
                          step="any"
                          value={draft[def.key] ?? ''}
                          min={def.minimum ?? undefined}
                          max={def.maximum ?? undefined}
                          onChange={e => setDraft(prev => ({ ...prev, [def.key]: e.target.value }))}
                        />
                      </td>
                      <td>{def.unit}</td>
                      <td className="muted">{asText(def.default)}</td>
                      <td className="muted">{def.minimum ?? '—'} ~ {def.maximum ?? '—'}</td>
                      <td className="muted">
                        {def.desc}
                        {def.impacts.length > 0 && <span className="muted small"> 影响：{def.impacts.join('、')}</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        ))}

        <div className="thr-actions">
          <input
            className="thr-note"
            placeholder="这次调整的原因（写进审计，可留空）"
            value={note}
            onChange={e => setNote(e.target.value)}
          />
          <button className="btn" type="button" disabled={busy || dirty === 0} onClick={() => { void onSave(); }}>
            保存为新版本{dirty > 0 ? '（' + dirty + ' 项改动）' : ''}
          </button>
          <button className="btn secondary" type="button" disabled={busy} onClick={() => { void onReset(); }}>恢复默认</button>
          <button className="link-btn" type="button" disabled={busy || dirty === 0} onClick={() => {
            setDraft(Object.fromEntries(Object.entries(data.values).map(([k, v]) => [k, asText(v)])));
            setError('');
          }}>放弃修改</button>
        </div>

        <h3>版本历史</h3>
        {data.history.length === 0 ? (
          <p className="muted">还没有自定义版本（当前是算法默认 v{data.version}）。</p>
        ) : (
          <table className="mini">
            <thead><tr><th>版本</th><th>备注</th><th>时间</th></tr></thead>
            <tbody>
              {data.history.map(h => (
                <tr key={h.version}>
                  <td>v{h.version}</td>
                  <td>{h.note ?? '—'}</td>
                  <td className="muted">{h.created_at ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
