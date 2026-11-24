import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { getThresholds, resetThresholds, saveThresholds, type ThresholdDef, type ThresholdHistoryItem } from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { getUser } from '../../auth/store';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';

/**
 * 风控参数。
 *
 * 规则：参数版本化，改一次升一版；**旧报告不重写**——报告里存的是当时的参数版本，
 * 所以这里改值只影响之后的分析。页面上把这句话写出来，避免有人以为改完历史会跟着变。
 */
export default function ThresholdsPage() {
  const { hash } = useLocation();
  const isAdmin = Boolean(getUser()?.is_admin);
  const [defs, setDefs] = useState<ThresholdDef[]>([]);
  const [values, setValues] = useState<Record<string, string | number | null>>({});
  const [savedValues, setSavedValues] = useState<Record<string, string | number | null>>({});
  const [history, setHistory] = useState<ThresholdHistoryItem[]>([]);
  const [version, setVersion] = useState<number | null>(null);
  const [note, setNote] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!hash || !defs.length) return;
    const el = document.getElementById(hash.slice(1));
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [hash, defs]);

  const dirtyCount = useMemo(
    () => defs.filter((d) => String(values[d.key] ?? '') !== String(savedValues[d.key] ?? '')).length,
    [defs, values, savedValues],
  );

  const load = useCallback(() => {
    getThresholds()
      .then((data) => {
        setDefs(data.defs ?? []);
        setValues(data.values ?? {});
        setSavedValues(data.values ?? {});
        setHistory(data.history ?? []);
        setVersion(data.version);
      })
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const groups = useMemo(() => Array.from(new Set(defs.map((item) => item.group))), [defs]);

  async function save() {
    setError('');
    setMessage('');
    // 前端前置校验：空串转 null，校验数字合法性与 min/max 边界
    const cleaned: Record<string, string | number | null> = {};
    for (const def of defs) {
      const raw = values[def.key];
      if (raw === '' || raw === null || raw === undefined) {
        cleaned[def.key] = null;
        continue;
      }
      const num = Number(raw);
      if (!Number.isFinite(num)) {
        setError(`参数「${def.label}」必须是有效数字`);
        return;
      }
      if (def.minimum !== null && def.minimum !== undefined && num < Number(def.minimum)) {
        setError(`参数「${def.label}」不能小于 ${def.minimum}`);
        return;
      }
      if (def.maximum !== null && def.maximum !== undefined && num > Number(def.maximum)) {
        setError(`参数「${def.label}」不能大于 ${def.maximum}`);
        return;
      }
      cleaned[def.key] = num;
    }
    try {
      const result = await saveThresholds(cleaned, note || undefined);
      setVersion(result.saved_version);
      setSavedValues(cleaned);
      setMessage('已保存为第 ' + result.saved_version + ' 版；旧报告仍按各自版本解释。');
      setNote('');
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    }
  }

  async function handleResetDefaults() {
    setError('');
    setMessage('');
    try {
      const res = await resetThresholds();
      setMessage(`已恢复系统默认阈值（保存为第 ${res.saved_version} 版）。`);
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    }
  }

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>风控参数</h1>
          <p className="sub">
            当前第 {version ?? '—'} 版，共 {defs.length} 项。改动只影响之后的分析，历史报告不重写。
          </p>
        </div>
        {isAdmin ? (
          <div className="filters">
            {dirtyCount > 0 ? <span className="pill warn">已改 {dirtyCount} 项未保存</span> : null}
            <Button variant="ghost" size="sm" disabled={dirtyCount === 0} onClick={() => setValues(savedValues)}>放弃修改</Button>
            <Button variant="ghost" size="sm" onClick={() => void handleResetDefaults()}>恢复默认</Button>
            <Button onClick={() => void save()}>保存为新版本</Button>
          </div>
        ) : <span className="muted small">只读（需管理员）</span>}
      </header>

      {error ? <Notice>{error}</Notice> : null}
      {message ? <Notice tone="ok">{message}</Notice> : null}

      {groups.map((group) => (
        <section key={group}>
          <h2>{group}</h2>
          <table className="grid compact">
            <thead>
              <tr><th>参数</th><th>值</th><th>范围</th><th>说明</th></tr>
            </thead>
            <tbody>
              {defs.filter((item) => item.group === group).map((item) => (
                <tr key={item.key} id={`def-${item.key}`} className={hash === `#def-${item.key}` ? 'active-row' : ''}>
                  <td>
                    {item.label}
                    {!item.calibrated ? <span className="pill warn" style={{ marginLeft: 6, fontSize: 11 }}>未校准</span> : null}
                    <div className="muted small">{item.key} · 默认 {item.default ?? '空'}</div>
                    {item.impacts?.length ? (
                      <div className="muted small">影响：{item.impacts.join('、')}</div>
                    ) : null}
                  </td>
                  <td>
                    <input
                      className="threshold-input"
                      disabled={!isAdmin}
                      value={values[item.key] ?? ''}
                      onChange={(event) => setValues({ ...values, [item.key]: event.target.value })}
                    />
                  </td>
                  <td className="muted small">
                    {item.minimum ?? '—'} ~ {item.maximum ?? '—'} {item.unit}
                  </td>
                  <td className="small muted">{item.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}

      {isAdmin ? (
        <div className="lab-save" style={{ marginTop: 10 }}>
          <input placeholder="改动备注（可空）" value={note} onChange={(event) => setNote(event.target.value)} />
        </div>
      ) : null}
      {history.length > 0 ? (
        <section style={{ marginTop: 20 }}>
          <h2>参数版本历史</h2>
          <table className="grid compact">
            <thead><tr><th>版本</th><th>备注</th><th>时间</th></tr></thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.version}>
                  <td className="mono">v{h.version}</td>
                  <td>{h.note || '—'}</td>
                  <td className="small muted">{h.created_at || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </div>
  );
}
