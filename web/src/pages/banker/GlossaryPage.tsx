import { useEffect, useMemo, useState } from 'react';
import { getMetricDefinitions, getVerificationDefinitions, type MetricDef, type VerificationDef } from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { Notice } from '../../ui/Notice';

/**
 * 口径说明：指标口径 + 校验口径。
 *
 * 这两张表是**只读的字典**，不是可调参数，所以不放在「参数」栏——
 * 参数栏只放能改的东西（风控阈值、OCR 路由）。这里从报告与特征 Lab 里按需跳到。
 */
export default function GlossaryPage() {
  const [tab, setTab] = useState<'metrics' | 'checks'>('metrics');
  const [metrics, setMetrics] = useState<MetricDef[]>([]);
  const [checks, setChecks] = useState<VerificationDef[]>([]);
  const [version, setVersion] = useState<number | null>(null);
  const [group, setGroup] = useState('');
  const [layer, setLayer] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    getMetricDefinitions()
      .then((data) => {
        setMetrics(data.items);
        setVersion(data.metric_set_version);
      })
      .catch((err) => setError(getErrorMessage(err, 'banker')));
    getVerificationDefinitions()
      .then((data) => setChecks(data.items))
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  }, []);

  const groups = useMemo(() => Array.from(new Set(metrics.map((item) => item.group))), [metrics]);
  const layers = useMemo(() => Array.from(new Set(checks.map((item) => item.layer))), [checks]);
  const shownMetrics = group ? metrics.filter((item) => item.group === group) : metrics;
  const shownChecks = layer ? checks.filter((item) => item.layer === layer) : checks;

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>口径说明</h1>
          <p className="sub">
            只读的字典：每项指标怎么算、每项自检怎么验。报告里点开任意指标都能跳回这里。
            {version ? ' 指标集版本 ' + version + '，历史报告按各自版本解释。' : ''}
          </p>
        </div>
        <div className="filters">
          <div className="tabs small-tabs">
            <button className={tab === 'metrics' ? 'active' : ''} onClick={() => setTab('metrics')}>
              指标口径（{metrics.length}）
            </button>
            <button className={tab === 'checks' ? 'active' : ''} onClick={() => setTab('checks')}>
              校验口径（{checks.length}）
            </button>
          </div>
        </div>
      </header>

      {error ? <Notice>{error}</Notice> : null}

      {tab === 'metrics' ? (
        <>
          <div className="filters" style={{ marginBottom: 12 }}>
            <select value={group} onChange={(event) => setGroup(event.target.value)}>
              <option value="">全部分区</option>
              {groups.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </div>
          <table className="grid compact">
            <thead><tr><th>代号</th><th>指标</th><th>单位</th><th>口径</th><th>输入</th></tr></thead>
            <tbody>
              {shownMetrics.map((item) => (
                <tr key={item.code}>
                  <td>{item.code}</td>
                  <td>{item.name}</td>
                  <td className="muted small">{item.unit}</td>
                  <td className="small">{item.formula}</td>
                  <td className="small muted">{item.inputs}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <>
          <div className="filters" style={{ marginBottom: 12 }}>
            <select value={layer} onChange={(event) => setLayer(event.target.value)}>
              <option value="">全部层</option>
              {layers.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </div>
          <table className="grid compact">
            <thead><tr><th>编号</th><th>层</th><th>方法</th></tr></thead>
            <tbody>
              {shownChecks.map((item) => (
                <tr key={item.code}>
                  <td>{item.code}</td>
                  <td>{item.layer}</td>
                  <td className="small">{item.method}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
