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
  // 列表输入框用本地文本做受控值：
  // 直接在 onChange 里 split 再 join 会把用户刚敲下的分隔符立刻吃掉，
  // 表现就是「填了第一个词以后再也打不进第二个」。
  const [customFor, setCustomFor] = useState<'meta' | 'table' | null>(null);
  const [newCode, setNewCode] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [kwText, setKwText] = useState(p.map.match_rule.bank_name_keywords.join('、'));
  const [fpText, setFpText] = useState(p.map.match_rule.header_fingerprint.join('、'));

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
          value={kwText}
          placeholder="页面里出现的银行名，用顿号分隔"
          onChange={e => { setKwText(e.target.value); p.onKeywords(splitList(e.target.value)); }}
        />
      </div>
      <div className="row">
        <label>表头词</label>
        <input
          type="text"
          value={fpText}
          placeholder="如 交易日期、摘要、发生额（顿号、逗号、空格都行）"
          onChange={e => { setFpText(e.target.value); p.onFingerprint(splitList(e.target.value)); }}
        />
      </div>
      <p className="muted small">
        表头词用于「按表头自动定列」：每页表头里都该出现的列名，写 3–5 个即可。
        用顿号分开，例如 <code>交易日期、摘要、发生额</code>；识别时只要有一半以上命中，就算这一页是明细页。
      </p>
      <p className="muted">
        基准尺寸：{p.map.page_size.w > 0 ? `${round4(p.map.page_size.w)} × ${round4(p.map.page_size.h)} pt` : '未记录'}
      </p>

      <h2>当前选中</h2>
      <div className="row"><label>对象</label><span className="muted">{currentLabel}</span></div>
      {target?.kind === 'meta' && (
        <>
          <div className="row">
            <label>字段</label>
            <select value={currentField} onChange={e => {
              if (e.target.value === '__custom__') { setCustomFor('meta'); return; }
              p.onAssign(e.target.value);
            }}>
              <option value="">（未指定）</option>
              <optgroup label="预设字段（账号、户名、期间等）">
                {options.filter(o => !o.label.includes('自定义')).map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
              </optgroup>
              {options.some(o => o.label.includes('自定义')) && (
                <optgroup label="这个模板里你自己加的">
                  {options.filter(o => o.label.includes('自定义')).map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
                </optgroup>
              )}
              <option value="__custom__">+ 新建一个字段…</option>
            </select>
          </div>
        </>
      )}
      {customFor && (
        <div className="row" style={{ flexDirection: 'column', alignItems: 'stretch', gap: 6 }}>
          <label>新建字段</label>
          <input placeholder="中文名，如 夜间消费笔数" value={newLabel} onChange={e => setNewLabel(e.target.value)} />
          <input placeholder="英文代号，如 night_cnt（小写字母开头）" value={newCode} onChange={e => setNewCode(e.target.value)} />
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn" type="button" onClick={() => {
              if (!CODE_PATTERN.test(newCode)) { p.onHint('代号只能小写字母开头，含小写字母/数字/下划线，2–31 位'); return; }
              if (!newLabel.trim()) { p.onHint('请填写中文名'); return; }
              p.onAddCustom({ code: newCode, label: newLabel.trim() });
              p.onAssign(newCode);
              setCustomFor(null); setNewCode(''); setNewLabel('');
            }}>创建并选中</button>
            <button className="link-btn" type="button" onClick={() => { setCustomFor(null); setNewCode(''); setNewLabel(''); }}>取消</button>
          </div>
          <p className="muted small">自定义字段属于这个模板：建一次，之后模板里所有字段框和列都能选它。</p>
        </div>
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