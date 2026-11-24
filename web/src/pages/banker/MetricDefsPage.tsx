import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  createCustomMetric,
  deleteCustomMetric,
  getMetricAtoms,
  getMetricDefinitions,
  listCustomMetrics,
  type CustomMetricItem,
  type MetricAtom,
  type MetricDef,
} from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { getUser } from '../../auth/store';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';

/** 指标口径：口径是业务资产，必须能查到「这一项算什么、缺什么就算不出来」。 */
export default function MetricDefsPage() {
  const isAdmin = Boolean(getUser()?.is_admin);
  const [items, setItems] = useState<MetricDef[]>([]);
  const [customs, setCustoms] = useState<CustomMetricItem[]>([]);
  const [atoms, setAtoms] = useState<MetricAtom[]>([]);
  const [version, setVersion] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [group, setGroup] = useState('');
  const [keyword, setKeyword] = useState('');
  const [newCode, setNewCode] = useState('');
  const [newName, setNewName] = useState('');
  const [newUnit, setNewUnit] = useState('');
  const [newGroupName, setNewGroupName] = useState('自定义');
  const [newInputs, setNewInputs] = useState('');
  const [newNote, setNewNote] = useState('');
  const [newFormula, setNewFormula] = useState('');
  const [steps, setSteps] = useState<{ atom: string; args?: Record<string, unknown> }[]>([]);
  const [selectedAtom, setSelectedAtom] = useState('');
  const [atomArgsJson, setAtomArgsJson] = useState('{}');

  const loadCustoms = useCallback(() => {
    listCustomMetrics()
      .then((res) => setCustoms(res.items ?? []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    Promise.all([getMetricDefinitions(), getMetricAtoms().catch(() => ({ items: [] as MetricAtom[] }))])
      .then(([data, atomsRes]) => {
        setItems(data.items);
        setVersion(data.metric_set_version);
        setAtoms(atomsRes.items ?? []);
        if (atomsRes.items?.length) setSelectedAtom(atomsRes.items[0].key);
      })
      .catch((err) => setError(getErrorMessage(err, 'banker')));
    loadCustoms();
  }, [loadCustoms]);

  const groups = useMemo(() => Array.from(new Set(items.map((item) => item.group))), [items]);
  const shown = items.filter((item) => {
    if (group && item.group !== group) return false;
    if (!keyword.trim()) return true;
    const q = keyword.trim().toLowerCase();
    return item.code.toLowerCase().includes(q) || item.name.toLowerCase().includes(q) || (item.formula || '').toLowerCase().includes(q);
  });

  function addStep() {
    if (!selectedAtom) return;
    let parsed: Record<string, unknown> = {};
    try {
      parsed = atomArgsJson.trim() ? JSON.parse(atomArgsJson) : {};
    } catch {
      setError('算子参数须为合法 JSON 对象，例如 {"direction":"out"}');
      return;
    }
    setError('');
    setSteps((prev) => [...prev, { atom: selectedAtom, args: parsed }]);
  }

  async function handleAddCustom() {
    if (!newCode.trim() || !newName.trim()) {
      setError('请填写自定义指标代号与名称');
      return;
    }
    setError('');
    try {
      await createCustomMetric({
        code: newCode.trim(),
        name: newName.trim(),
        unit: newUnit.trim() || undefined,
        group_name: newGroupName.trim() || undefined,
        inputs: newInputs.trim() || undefined,
        note: newNote.trim() || undefined,
        formula: newFormula.trim() || undefined,
        steps: steps.length ? steps : undefined,
      });
      setNewCode('');
      setNewName('');
      setNewUnit('');
      setNewInputs('');
      setNewNote('');
      setNewFormula('');
      setSteps([]);
      setNotice('已新增自定义指标（含可视化步骤配置）。');
      loadCustoms();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    }
  }

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>指标口径</h1>
          <p className="sub">
            共 {items.length} 项 · 指标集版本 {version ?? '—'}。口径只增不改，历史报告按当时版本解释。
          </p>
        </div>
        <div className="filters">
          <input
            className="search"
            placeholder="搜索代号 / 指标名 / 口径"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <select value={group} onChange={(event) => setGroup(event.target.value)}>
            <option value="">全部分区</option>
            {groups.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>
      </header>

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="ok">{notice}</Notice> : null}

      <table className="grid compact">
        <thead>
          <tr><th>代号</th><th>指标</th><th>单位</th><th>口径</th><th>输入</th></tr>
        </thead>
        <tbody>
          {shown.map((item) => (
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
      <section style={{ marginTop: 22 }}>
        <h2>自定义指标（{customs.length}）· 可视化原子积木编排</h2>
        {isAdmin ? (
          <div className="import-box" style={{ marginBottom: 12 }}>
            <div className="filters" style={{ marginBottom: 8 }}>
              <input placeholder="代号，如 night_out" value={newCode} onChange={(e) => setNewCode(e.target.value)} />
              <input placeholder="中文名称" value={newName} onChange={(e) => setNewName(e.target.value)} />
              <input placeholder="单位（如 % / 元 / 笔）" value={newUnit} onChange={(e) => setNewUnit(e.target.value)} style={{ width: 130 }} />
              <input placeholder="分组" value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} style={{ width: 100 }} />
              <input placeholder="依赖列，如 金额,方向" value={newInputs} onChange={(e) => setNewInputs(e.target.value)} />
              <input placeholder="口径说明" value={newFormula} onChange={(e) => setNewFormula(e.target.value)} />
              <input placeholder="备注" value={newNote} onChange={(e) => setNewNote(e.target.value)} />
            </div>
            {atoms.length > 0 ? (
              <div className="filters" style={{ marginBottom: 8 }}>
                <select value={selectedAtom} onChange={(e) => setSelectedAtom(e.target.value)} aria-label="选择算子积木">
                  {atoms.map((a) => (
                    <option key={a.key} value={a.key}>
                      {a.label} ({a.key}) · {a.detail}
                    </option>
                  ))}
                </select>
                <input
                  placeholder='参数 JSON，如 {"direction":"out"}'
                  value={atomArgsJson}
                  onChange={(e) => setAtomArgsJson(e.target.value)}
                  style={{ width: 220 }}
                />
                <Button size="sm" variant="ghost" onClick={addStep}>+ 添加计算步骤</Button>
                {steps.length > 0 ? (
                  <span className="small muted">
                    已编排 {steps.length} 步：{steps.map((s) => s.atom).join(' → ')}
                  </span>
                ) : null}
                <Button size="sm" onClick={() => void handleAddCustom()}>保存自定义指标</Button>
              </div>
            ) : (
              <Button size="sm" onClick={() => void handleAddCustom()}>新增指标</Button>
            )}
          </div>
        ) : null}
        {customs.length ? (
          <table className="grid compact">
            <thead><tr><th>代号</th><th>名称</th><th>分组</th><th>口径 / 编排步骤</th>{isAdmin ? <th>操作</th> : null}</tr></thead>
            <tbody>
              {customs.map((c) => (
                <tr key={c.id}>
                  <td className="mono small">{c.code}</td>
                  <td>{c.name}{c.unit ? <span className="muted small"> ({c.unit})</span> : null}</td>
                  <td className="small muted">{c.group_name || '自定义'}</td>
                  <td className="small muted">
                    {c.formula || c.note || '—'}
                    {c.steps?.length ? <span className="pill" style={{ marginLeft: 6 }}>{c.steps.length} 步积木</span> : null}
                  </td>
                  {isAdmin ? (
                    <td>
                      <button type="button" className="link-btn danger" onClick={() => void deleteCustomMetric(c.id).then(loadCustoms)}>
                        删除
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted small">暂未登记自定义指标。</p>}
      </section>
    </div>
  );
}
