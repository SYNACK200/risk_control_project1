import { useEffect, useState } from 'react';
import { FIELD_DICT } from '../lib/fields';
import type { FieldMapV1, Selection } from '../lib/types';

/**
 * 列清单：已标注字段的查看与编辑。
 *
 * 从 Annotate.tsx 抽出来单独成文件——那个文件 1000 多行，任何 JSX 改动都会连带崩，
 * 抽出后这里的字段增删、自定义字段输入、选中联动都能独立改、独立验证。
 */
export function ColumnFieldList({
  map, sel, onSelect, onUpdateColumn, onRemoveColumn, onRemoveColumnField,
  onAddCustomField,
}: {
  map: FieldMapV1;
  sel: Selection | null;
  onSelect: (s: Selection) => void;
  onUpdateColumn: (tableId: string, index: number, patch: Record<string, unknown>) => void;
  onRemoveColumn: (tableId: string, index: number) => void;
  onRemoveColumnField: (tableId: string, index: number, codes: string[], code: string) => void;
  onAddCustomField: (code: string) => void;
}) {
  // 自定义字段就地输入（不弹 window.prompt）
  const [customFor, setCustomFor] = useState<{ tableId: string; index: number } | null>(null);
  const [customCode, setCustomCode] = useState('');
  // 给已有列加属性
  const [attrFor, setAttrFor] = useState<{ tableId: string; index: number; codes: string[] } | null>(null);

  /** 提交自定义字段：校验代号格式，登记字典，再绑到这一列。 */
  function commitCustom(
    tableId: string, index: number, raw: string,
    addCustom: (code: string) => void,
    updateColumn: (tableId: string, index: number, patch: Record<string, unknown>) => void,
    setFor: (v: null) => void, setCode: (v: string) => void,
  ) {
    const code = raw.trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]{1,30}$/.test(code)) {
      window.alert('代号只能用字母、数字、下划线，且以字母或下划线开头（如 night_ratio）');
      return;
    }
    addCustom(code);
    updateColumn(tableId, index, { field: code, fields: [code] });
    setFor(null); setCode('');
  }

  // 画布上点选某列 → 右栏对应行滚到可见并高亮（原来只有右栏→画布的单向映射）
  useEffect(() => {
    if (!sel || sel.kind !== 'column') return;
    const el = document.getElementById('col-' + sel.tableId + '-' + sel.index);
    if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [sel]);

  if (map.tables.length === 0) return null;

  return (
    <section className="column-list">
            <div className="column-list-head">
              已标注字段（{map.tables.reduce((n, tb) => n + tb.columns.length, 0)} 列）
              <span className="muted small"> · 可改字段、一列加多个属性、删除或定位；字段支持自定义</span>
            </div>
            {map.tables.map((tb, ti) => (
              <div key={tb.id} className="column-table">
                <div className="muted small">表格 {ti + 1}（第 {tb.page} 页）· {tb.columns.length} 列</div>
                {tb.columns.length === 0 && <div className="muted small">还没有列：用「列」工具在画布上点选一列数据。</div>}
                {tb.columns.map((c, i) => {
                  const codes = c.fields && c.fields.length ? c.fields : (c.field ? [c.field] : []);
                  return (
                    <div
                      className={'column-row' + (sel?.kind === 'column' && sel.tableId === tb.id && sel.index === i ? ' active' : '')}
                      key={i}
                      id={'col-' + tb.id + '-' + i}
                    >
                      <button className="link-btn" type="button"
                        onClick={() => { onSelect({ kind: 'column', tableId: tb.id, index: i }); }}>
                        #{i + 1}
                      </button>
                      <span className="muted small">x {c.x.toFixed(3)} · w {c.w.toFixed(3)}</span>
                      <select value={c.field}
                        onChange={e => {
                          const v = e.target.value;
                          if (v === '__custom__') {
                            // 就地输入代号：不弹系统框，和页面风格一致
                            setCustomFor({ tableId: tb.id, index: i });
                            setCustomCode('');
                            return;
                          }
                          onUpdateColumn(tb.id, i, { field: v, fields: [v] });
                        }}>
                        <option value="">（未指定）</option>
                        {FIELD_DICT.filter(f => f.scope !== 'meta').map(f => (
                          <option key={f.code} value={f.code}>{f.label}（{f.code}）</option>
                        ))}
                        {map.custom_fields.map(f => (
                          <option key={f.code} value={f.code}>{f.label}（自定义）</option>
                        ))}
                        <option value="__custom__">+ 自定义字段…</option>
                      </select>
                      {codes.slice(1).map(code => (
                        <span className="field-chip" key={code}>
                          {code}
                          <button className="link-btn" type="button"
                            onClick={() => onRemoveColumnField(tb.id, i, codes, code)}>×</button>
                        </span>
                      ))}
                      <button className="link-btn" type="button"
                        onClick={() => { setAttrFor({ tableId: tb.id, index: i, codes }); }}>＋属性</button>
                      <button className="link-btn danger-text" type="button"
                        onClick={() => onRemoveColumn(tb.id, i)}>删除</button>
                    </div>
                  );
                })}

                {/* 自定义字段：就地输入代号，不弹系统框 */}
                {customFor && customFor.tableId === tb.id && (
                  <div className="inline-field">
                    <input
                      placeholder="英文代号，如 night_ratio"
                      value={customCode}
                      onChange={e => setCustomCode(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') { commitCustom(tb.id, customFor.index, customCode, onAddCustomField, onUpdateColumn, setCustomFor, setCustomCode); } }}
                    />
                    <button className="btn" type="button"
                      onClick={() => commitCustom(tb.id, customFor.index, customCode, onAddCustomField, onUpdateColumn, setCustomFor, setCustomCode)}>确定</button>
                    <button className="link-btn" type="button" onClick={() => { setCustomFor(null); setCustomCode(''); }}>取消</button>
                  </div>
                )}

                {/* 给已有列再加一个属性 */}
                {attrFor && attrFor.tableId === tb.id && (
                  <div className="inline-field">
                    <select
                      defaultValue=""
                      onChange={e => {
                        const code = e.target.value;
                        if (!code) return;
                        onUpdateColumn(tb.id, attrFor.index, { fields: [...attrFor.codes, code] });
                        setAttrFor(null);
                      }}>
                      <option value="">选一个要加的属性…</option>
                      {FIELD_DICT.filter(f => f.scope !== 'meta' && !attrFor.codes.includes(f.code)).map(f => (
                        <option key={f.code} value={f.code}>{f.label}（{f.code}）</option>
                      ))}
                    </select>
                    <button className="link-btn" type="button" onClick={() => setAttrFor(null)}>取消</button>
                  </div>
                )}
              </div>
            ))}
    </section>
  );
}