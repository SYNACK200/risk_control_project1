import { useState } from 'react';
import type { CustomField, FieldMapV1, Selection } from '../lib/types';
import { fieldsForScope, labelOf, CODE_PATTERN } from '../lib/fields';
import { round4 } from '../lib/template';

interface Props {
  map: FieldMapV1;
  sel: Selection;
  onBankCode: (v: string) => void;
  onKeywords: (v: string[]) => void;
  onFingerprint: (v: string[]) => void;
  onAssign: (field: string) => void;
  onHeaderY: (y: number | undefined) => void;
  onDelete: () => void;
  onAddCustom: (f: CustomField) => void;
  onRemoveCustom: (code: string) => void;
  onHint: (text: string) => void;
}

export function Inspector(p: Props) {
  const [code, setCode] = useState('');
  const [label, setLabel] = useState('');

  const target = p.sel;
  const scope = target?.kind === 'column' || target?.kind === 'table' ? 'table' : 'meta';
  const options = fieldsForScope(scope, p.map.custom_fields);

  let currentField = '';
  let currentLabel = '未选中';
  if (target?.kind === 'meta') {
    const box = p.map.meta_boxes.find(b => b.id === target.id);
    currentField = box?.field ?? '';
    currentLabel = `字段框 · ${box?.field ? labelOf(box.field, p.map.custom_fields) : '未指定'}`;
  } else if (target?.kind === 'table') {
    const table = p.map.tables.find(t => t.id === target.id);
    currentLabel = `表格区 · ${table?.columns.length ?? 0} 列`;
  } else if (target?.kind === 'column') {
    const table = p.map.tables.find(t => t.id === target.tableId);
    const col = table?.columns[target.index];
    currentField = col?.field ?? '';
    currentLabel = `列 · ${col?.field ? labelOf(col.field, p.map.custom_fields) : '未指定'}`;
  }

  function addCustom() {
    if (!CODE_PATTERN.test(code)) {
      p.onHint('字段编码只能用小写字母开头，含小写字母、数字、下划线，2–31 位');
      return;
    }
    if (!label.trim()) { p.onHint('请填写中文名'); return; }
    p.onAddCustom({ code, label: label.trim() });
    setCode('');
    setLabel('');
  }

  return (
    <div>
      <h2>版式信息</h2>
      <div className="row">
        <label>银行</label>
        <input type="text" value={p.map.bank_code} placeholder="如 ICBC" onChange={e => p.onBankCode(e.target.value)} />
      </div>
      <div className="row">
        <label>银行名</label>
        <input
          type="text"
          value={p.map.match_rule.bank_name_keywords.join('、')}
          placeholder="页面里出现的银行名，逗号分隔"
          onChange={e => p.onKeywords(splitList(e.target.value))}
        />
      </div>
      <div className="row">
        <label>表头词</label>
        <input
          type="text"
          value={p.map.match_rule.header_fingerprint.join('、')}
          placeholder="如 交易日期、摘要、发生额"
          onChange={e => p.onFingerprint(splitList(e.target.value))}
        />
      </div>
      <p className="muted">
        基准尺寸：{p.map.page_size.w > 0 ? `${round4(p.map.page_size.w)} × ${round4(p.map.page_size.h)} pt` : '未记录'}
      </p>

      <h2>当前选中</h2>
      <div className="row"><label>对象</label><span className="muted">{currentLabel}</span></div>
      {target?.kind === 'meta' && (
        <>
          <div className="row">
            <label>字段</label>
            <select value={currentField} onChange={e => p.onAssign(e.target.value)}>
              <option value="">（未指定）</option>
              {options.map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
            </select>
          </div>
        </>
      )}
      {target?.kind === 'table' && (
        <>
          <p className="muted">先选表格区，再点「画列边界」在区域内拖出每一列。</p>
          <div className="row">
            <label>表头高度</label>
            <input
              type="number"
              step="0.001"
              min="0"
              max="1"
              value={p.map.tables.find(t => t.id === target.id)?.headerY ?? ''}
              placeholder="可选，0–1 的相对位置"
              onChange={e => p.onHeaderY(e.target.value === '' ? undefined : Number(e.target.value))}
            />
          </div>
        </>
      )}
      <div className="row">
        <button className="btn danger" disabled={!target} onClick={p.onDelete}>删除选中</button>
      </div>

      <h2>自定义字段</h2>
      <div className="row">
        <input type="text" value={code} placeholder="编码 如 branch_code" onChange={e => setCode(e.target.value)} />
        <input type="text" value={label} placeholder="中文名 如 开户网点" onChange={e => setLabel(e.target.value)} />
        <button className="btn" onClick={addCustom}>添加</button>
      </div>
      {p.map.custom_fields.length === 0 && <p className="muted">还没有自定义字段。内置字段不够时再加。</p>}
      {p.map.custom_fields.map(cf => (
        <div className="row" key={cf.code}>
          <span className="mono" style={{ fontSize: 12 }}>{cf.code}</span>
          <span className="muted">{cf.label}</span>
          <button className="btn danger" style={{ marginLeft: 'auto' }} onClick={() => p.onRemoveCustom(cf.code)}>移除</button>
        </div>
      ))}

      <h2>统计</h2>
      <p className="muted">
        字段框 {p.map.meta_boxes.length} · 表格区 {p.map.tables.length} · 列 {""}
        {p.map.tables.reduce((n, t) => n + t.columns.length, 0)}
      </p>
    </div>
  );
}

function splitList(v: string): string[] {
  return v.split(/[、,，;；\s]+/).map(s => s.trim()).filter(Boolean);
}