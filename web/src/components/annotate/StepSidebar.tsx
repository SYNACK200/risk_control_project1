import { useEffect, useState } from 'react';
import { type LabSample } from '../../api/lab';
import {
  type HeaderFieldSpec,
  type ShortFieldSpec,
  type TaskSummary,
  type TemplateRow,
} from '../../api/banker';
import { Button } from '../../ui/Button';
import {
  allFieldOptions,
  allSingleFieldOptions,
  BANK_OPTIONS,
  bankLabel,
  BOX_COLORS,
  DEFAULT_HEADER_FIELDS,
  DEFAULT_SHORT_FIELDS,
  fieldLabel,
  type ColumnBox,
  type CustomFieldOption,
  type SingleBox,
  type TableRegionBox,
} from './types';

export type ValidationIssue = {
  code: string;
  level: 'error' | 'warn';
  message: string;
  target?: { kind: 'region' | 'col' | 'single'; id: string };
};

type Props = {
  samples: LabSample[];
  tasks: TaskSummary[];
  templates: TemplateRow[];
  sourceMode: 'sample' | 'file' | 'task' | 'template';
  sourceLabel: string;
  onSelectSample: (sampleName: string) => void;
  onSelectFile: (file: File) => void;
  onSelectTask: (taskId: number) => void;
  onSelectTemplate: (templateId: number) => void;
  keepLayoutOnUpload: boolean;
  onToggleKeepLayout: (v: boolean) => void;
  onAnalyzeFields: (shortSpecs: ShortFieldSpec[], headerSpecs: HeaderFieldSpec[]) => void;
  needPassword: boolean;
  password: string;
  onPasswordChange: (val: string) => void;
  onRetryWithPassword: () => void;
  bankCode: string;
  onBankCodeChange: (code: string) => void;
  pageRegions: TableRegionBox[];
  activeRegionId: string | null;
  onSelectRegion: (id: string) => void;
  onDeleteRegion: (id: string) => void;
  onStartDrawArea: () => void;
  columns: ColumnBox[];
  selected: { kind: 'region' | 'col' | 'single'; id: string } | null;
  onSelect: (sel: { kind: 'region' | 'col' | 'single'; id: string } | null) => void;
  onUpdateColumn: (id: string, patch: Partial<ColumnBox>) => void;
  onDeleteColumn: (id: string) => void;
  onStartDrawCol: () => void;
  singles: SingleBox[];
  onUpdateSingle: (id: string, patch: Partial<SingleBox>) => void;
  onDeleteSingle: (id: string) => void;
  onStartDrawSingle: () => void;
  customFields: CustomFieldOption[];
  onAddCustomField: (opt: CustomFieldOption) => void;
  requiredFields: string[];
  onToggleRequired: (fieldKey: string) => void;
  keyword: string;
  onKeywordChange: (val: string) => void;
  onSpread: () => void;
  onDryRun: () => void;
  onSaveTemplate: (publish: boolean) => void;
  onReparseTask?: () => void;
  validationIssues: ValidationIssue[];
  editingTemplateId: number | null;
  editingTaskId: number | null;
  isAdmin: boolean;
  busy: boolean;
};

export function StepSidebar({
  samples,
  tasks,
  templates,
  sourceMode,
  sourceLabel,
  onSelectSample,
  onSelectFile,
  onSelectTask,
  onSelectTemplate,
  keepLayoutOnUpload,
  onToggleKeepLayout,
  onAnalyzeFields,
  needPassword,
  password,
  onPasswordChange,
  onRetryWithPassword,
  bankCode,
  onBankCodeChange,
  pageRegions,
  activeRegionId,
  onSelectRegion,
  onDeleteRegion,
  onStartDrawArea,
  columns,
  selected,
  onSelect,
  onUpdateColumn,
  onDeleteColumn,
  onStartDrawCol,
  singles,
  onUpdateSingle,
  onDeleteSingle,
  onStartDrawSingle,
  customFields,
  onAddCustomField,
  requiredFields,
  onToggleRequired,
  keyword,
  onKeywordChange,
  onSpread,
  onDryRun,
  onSaveTemplate,
  onReparseTask,
  validationIssues,
  editingTemplateId,
  editingTaskId,
  isAdmin,
  busy,
}: Props) {
  const [customBankMode, setCustomBankMode] = useState(
    Boolean(bankCode && !BANK_OPTIONS.some((b) => b.code === bankCode)),
  );
  useEffect(() => {
    setCustomBankMode(Boolean(bankCode && !BANK_OPTIONS.some((b) => b.code === bankCode)));
  }, [bankCode]);
  const [addingCustomField, setAddingCustomField] = useState(false);
  const [newFieldCode, setNewFieldCode] = useState('');
  const [newFieldLabel, setNewFieldLabel] = useState('');
  const [newFieldKind, setNewFieldKind] = useState<'header' | 'short'>('header');
  const [expandedColId, setExpandedColId] = useState<string | null>(null);
  const [smartOpen, setSmartOpen] = useState(false);
  const [shortSpecs, setShortSpecs] = useState<ShortFieldSpec[]>(() =>
    DEFAULT_SHORT_FIELDS.map((item) => ({ ...item })),
  );
  const [headerSpecs, setHeaderSpecs] = useState<HeaderFieldSpec[]>(() =>
    DEFAULT_HEADER_FIELDS.map((item) => ({ ...item })),
  );

  const fieldOptions = allFieldOptions(customFields);
  const singleOptions = allSingleFieldOptions(customFields);
  const activeRegionCols = columns
    .filter((c) => c.regionId === activeRegionId)
    .sort((a, b) => a.x - b.x);

  const handleCreateCustomField = () => {
    const label = newFieldLabel.trim();
    if (!label) return;
    const prefix = newFieldKind === 'short' ? 'short_' : 'custom_';
    const rawCode =
      newFieldCode.trim().replace(/[^a-zA-Z0-9_]/g, '_') || prefix + Date.now().toString(36).slice(-4);
    const key = rawCode.toLowerCase();
    onAddCustomField({ key, label, kind: newFieldKind });
    if (newFieldKind === 'short') {
      setShortSpecs((prev) => (prev.some((s) => s.field === key) ? prev : [...prev, { field: key, label, keywords: label }]));
    } else {
      setHeaderSpecs((prev) => (prev.some((h) => h.field === key) ? prev : [...prev, { field: key, label, keywords: label }]));
    }
    setNewFieldCode('');
    setNewFieldLabel('');
    setAddingCustomField(false);
  };

  return (
    <aside className="ann-sidebar">
      {editingTemplateId && (
        <div className="ann-context-pill">
          正在编辑模板 <strong>#{editingTemplateId}</strong>（保存将生成新版）
        </div>
      )}
      {editingTaskId && (
        <div className="ann-context-pill warn">
          来自任务 <strong>#{editingTaskId}</strong>（支持临时重解析或沉淀为模板）
        </div>
      )}

      <section className="ann-step">
        <div className="ann-step-head">
          <span className="ann-step-num">1</span>
          <strong>导入流水样本</strong>
        </div>
        <div className="ann-source-tabs">
          <label className="ann-file-btn">
            上传 PDF / 图片 / ZIP
            <input
              type="file"
              accept=".pdf,.zip,image/png,image/jpeg,image/webp"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onSelectFile(f);
                e.target.value = '';
              }}
            />
          </label>
          <select
            aria-label="从模板库载入"
            value={editingTemplateId ? String(editingTemplateId) : ''}
            onChange={(e) => e.target.value && onSelectTemplate(Number(e.target.value))}
          >
            <option value="">载入已有模板…</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                #{t.id} {bankLabel(t.bank_code)} v{t.version} ({t.status === 'enabled' ? '在用' : t.status === 'draft' ? '草稿' : '停用'})
              </option>
            ))}
          </select>
          <select
            aria-label="选择内置样本"
            value={sourceMode === 'sample' ? sourceLabel : ''}
            onChange={(e) => e.target.value && onSelectSample(e.target.value)}
          >
            <option value="">内置测试样本…</option>
            {samples.map((s) => (
              <option key={s.name} value={s.name}>
                [{s.group}] {s.name.split('/').pop()}
              </option>
            ))}
          </select>
          <select
            aria-label="从已有任务导入"
            value=""
            onChange={(e) => e.target.value && onSelectTask(Number(e.target.value))}
          >
            <option value="">从近期任务取原件…</option>
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>
                #{t.id} · {t.bank_name || t.biz_no}
              </option>
            ))}
          </select>
        </div>
        {(columns.length > 0 || singles.length > 0) && (
          <label className="inline-check small" style={{ marginTop: 6, display: 'flex', gap: 6, alignItems: 'center' }}>
            <input
              type="checkbox"
              checked={keepLayoutOnUpload}
              onChange={(e) => onToggleKeepLayout(e.target.checked)}
            />
            <span>换样本或解锁时保留当前画布框选（方便给导入/无样本模板配参考文件）</span>
          </label>
        )}
        {sourceLabel && <div className="ann-source-current">当前：{sourceLabel}</div>}
        {needPassword && (
          <div className="ann-password-box">
            <input
              type="password"
              placeholder="输入 PDF 打开口令"
              value={password}
              onChange={(e) => onPasswordChange(e.target.value)}
            />
            <Button size="sm" onClick={onRetryWithPassword} disabled={busy}>
              解锁分析
            </Button>
          </div>
        )}
      </section>

      <section className="ann-step">
        <div className="ann-step-head">
          <span className="ann-step-num">2</span>
          <strong>选择所属银行与表格区</strong>
        </div>
        <div className="ann-row">
          {!customBankMode ? (
            <select
              value={BANK_OPTIONS.some((b) => b.code === bankCode) ? bankCode : ''}
              onChange={(e) => onBankCodeChange(e.target.value)}
            >
              <option value="">请选择银行 / 渠道…</option>
              {BANK_OPTIONS.map((b) => (
                <option key={b.code} value={b.code}>
                  {b.label} ({b.code})
                </option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              placeholder="输入银行编码（如 BOB / HXB）"
              value={bankCode}
              onChange={(e) => onBankCodeChange(e.target.value.toUpperCase())}
            />
          )}
          <button type="button" className="ann-link-btn" onClick={() => setCustomBankMode((v) => !v)}>
            {customBankMode ? '选常用银行' : '其他银行'}
          </button>
        </div>

        <div className="ann-region-bar">
          {pageRegions.map((r, idx) => (
            <div key={r.id} className="ann-region-chip-wrap">
              <button
                type="button"
                className={r.id === activeRegionId ? 'ann-region-chip active' : 'ann-region-chip'}
                onClick={() => {
                  onSelectRegion(r.id);
                  onSelect({ kind: 'region', id: r.id });
                }}
              >
                表格区 {idx + 1} ({r.slot})
              </button>
              {pageRegions.length > 1 && (
                <button
                  type="button"
                  className="ann-chip-del"
                  title="删除这个表格区"
                  onClick={() => onDeleteRegion(r.id)}
                >
                  ×
                </button>
              )}
            </div>
          ))}
          <button type="button" className="ann-link-btn" onClick={onStartDrawArea}>
            + 框选新表格区
          </button>
        </div>
      </section>

      <section className="ann-step">
        <div className="ann-step-head">
          <span className="ann-step-num">3</span>
          <strong>核对列与单值字段</strong>
          <div className="ann-step-actions">
            <button type="button" className="ann-link-btn" onClick={onStartDrawCol}>
              + 框新列
            </button>
            <button type="button" className="ann-link-btn" onClick={() => setAddingCustomField((v) => !v)}>
              + 自定义字段
            </button>
          </div>
        </div>

        {addingCustomField && (
          <div className="ann-custom-field-form">
            <select
              value={newFieldKind}
              onChange={(e) => setNewFieldKind(e.target.value as 'header' | 'short')}
            >
              <option value="header">标题字段（表格列）</option>
              <option value="short">短字段（页眉单值）</option>
            </select>
            <input
              type="text"
              placeholder={newFieldKind === 'short' ? '短字段名称（如 打印时间 / 客户经理）' : '中文列名（如 交易渠道 / 币种）'}
              value={newFieldLabel}
              onChange={(e) => setNewFieldLabel(e.target.value)}
            />
            <input
              type="text"
              placeholder="英文代号（可留空自动生成）"
              value={newFieldCode}
              onChange={(e) => setNewFieldCode(e.target.value)}
            />
            <Button size="sm" onClick={handleCreateCustomField}>
              添加
            </Button>
          </div>
        )}

        <div style={{ marginBottom: 8 }}>
          <button
            type="button"
            className="ann-link-btn"
            onClick={() => setSmartOpen((v) => !v)}
          >
            {smartOpen ? '▾ 收起两类字段智能分析面板' : '▸ 输入「短字段 + 标题字段」调算法自动框选'}
          </button>
          {smartOpen && (
            <div style={{ marginTop: 6, padding: 8, border: '1px solid #d8dee9', borderRadius: 6, background: '#f8fafc', fontSize: 12 }}>
              <div className="small muted" style={{ marginBottom: 4 }}>
                短字段（就近匹配页眉键值）：
              </div>
              {shortSpecs.map((sf, idx) => (
                <div key={idx} style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                  <input
                    style={{ width: 72, fontSize: 11 }}
                    value={sf.label}
                    placeholder="字段名"
                    onChange={(e) =>
                      setShortSpecs((p) => p.map((x, i) => (i === idx ? { ...x, label: e.target.value } : x)))
                    }
                  />
                  <input
                    style={{ flex: 1, fontSize: 11 }}
                    value={sf.keywords}
                    placeholder="锚点词（逗号分隔）"
                    onChange={(e) =>
                      setShortSpecs((p) => p.map((x, i) => (i === idx ? { ...x, keywords: e.target.value } : x)))
                    }
                  />
                  <button
                    type="button"
                    className="ann-mini-btn danger"
                    onClick={() => setShortSpecs((p) => p.filter((_, i) => i !== idx))}
                  >
                    ×
                  </button>
                </div>
              ))}
              <div style={{ display: 'flex', justifyContent: 'space-between', margin: '4px 0 6px' }}>
                <button
                  type="button"
                  className="ann-link-btn"
                  onClick={() =>
                    setShortSpecs((p) => [...p, { field: `short_${p.length + 1}`, label: '', keywords: '' }])
                  }
                >
                  + 加短字段
                </button>
              </div>
              <div className="small muted" style={{ marginBottom: 4 }}>
                标题字段（版式分析明细列）：
              </div>
              {headerSpecs.map((hf, idx) => (
                <div key={idx} style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                  <input
                    style={{ width: 72, fontSize: 11 }}
                    value={hf.label}
                    placeholder="列名"
                    onChange={(e) =>
                      setHeaderSpecs((p) => p.map((x, i) => (i === idx ? { ...x, label: e.target.value } : x)))
                    }
                  />
                  <input
                    style={{ flex: 1, fontSize: 11 }}
                    value={hf.keywords}
                    placeholder="表头词（逗号分隔）"
                    onChange={(e) =>
                      setHeaderSpecs((p) => p.map((x, i) => (i === idx ? { ...x, keywords: e.target.value } : x)))
                    }
                  />
                  <button
                    type="button"
                    className="ann-mini-btn danger"
                    onClick={() => setHeaderSpecs((p) => p.filter((_, i) => i !== idx))}
                  >
                    ×
                  </button>
                </div>
              ))}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
                <button
                  type="button"
                  className="ann-link-btn"
                  onClick={() =>
                    setHeaderSpecs((p) => [...p, { field: `col_${p.length + 1}`, label: '', keywords: '' }])
                  }
                >
                  + 加标题字段
                </button>
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() =>
                    onAnalyzeFields(
                      shortSpecs.filter((x) => x.field.trim() && (x.label.trim() || x.keywords.trim())),
                      headerSpecs.filter((x) => x.field.trim() && (x.label.trim() || x.keywords.trim())),
                    )
                  }
                >
                  {busy ? '分析中…' : '执行智能识别并画框'}
                </Button>
              </div>
            </div>
          )}
        </div>

        <div className="ann-spread-row">
          <input
            type="text"
            placeholder="点词识别列名，如：摘要 / 对方户名"
            value={keyword}
            onChange={(e) => onKeywordChange(e.target.value)}
          />
          <Button size="sm" variant="secondary" onClick={onSpread} disabled={busy || !keyword.trim()}>
            识别一列
          </Button>
        </div>

        <div className="ann-col-list">
          {activeRegionCols.length === 0 ? (
            <div className="ann-empty-hint">
              当前表格区还没有列框。点上方「+ 框新列」直接在表头和数值列上拖出方框即可。
            </div>
          ) : (
            activeRegionCols.map((col, idx) => {
              const color = BOX_COLORS[idx % BOX_COLORS.length];
              const isSel = selected?.kind === 'col' && selected.id === col.id;
              const isExp = expandedColId === col.id;
              return (
                <div
                  key={col.id}
                  className={`ann-col-item ${isSel ? 'selected' : ''}`}
                  onClick={() => onSelect({ kind: 'col', id: col.id })}
                >
                  <div className="ann-col-item-row">
                    <span className="ann-dot" style={{ background: color }} />
                    <select
                      value={col.field}
                      onChange={(e) => onUpdateColumn(col.id, { field: e.target.value })}
                    >
                      {fieldOptions.map((opt) => (
                        <option key={opt.key} value={opt.key}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="ann-mini-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpandedColId(isExp ? null : col.id);
                      }}
                    >
                      {col.cells.length ? `${col.cells.length}格` : '手动框'}
                    </button>
                    <button
                      type="button"
                      className="ann-mini-btn danger"
                      title="删除这一列"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteColumn(col.id);
                      }}
                    >
                      ×
                    </button>
                  </div>
                  {!isExp && col.cells.length > 0 && (
                    <div className="small muted" style={{ fontSize: 11, marginTop: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      样例：{col.cells.slice(0, 3).map((c) => c.text).join(' · ')}
                    </div>
                  )}
                  {isExp && (
                    <div className="ann-col-preview">
                      <div>
                        位置：x {(col.x * 100).toFixed(1)}% · 宽 {(col.w * 100).toFixed(1)}% · 来源 {col.source}
                      </div>
                      <label style={{ display: 'block', fontSize: 11, marginTop: 4 }} onClick={(e) => e.stopPropagation()}>
                        原件表头文本：
                        <input
                          style={{ width: '100%', fontSize: 11, marginTop: 2 }}
                          value={col.headerText ?? ''}
                          placeholder={fieldLabel(col.field, customFields)}
                          onChange={(e) => onUpdateColumn(col.id, { headerText: e.target.value })}
                        />
                      </label>
                      <div style={{ marginTop: 4, fontSize: 11 }} onClick={(e) => e.stopPropagation()}>
                        一列多字段（可选合并绑定）：
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 2 }}>
                          {fieldOptions.slice(0, 10).map((opt) => {
                            const fList = col.fields?.length ? col.fields : [col.field];
                            const checked = fList.includes(opt.key);
                            return (
                              <label key={opt.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  disabled={checked && fList.length === 1}
                                  onChange={() => {
                                    const next = checked
                                      ? fList.filter((k) => k !== opt.key)
                                      : [...fList, opt.key];
                                    onUpdateColumn(col.id, { field: next[0] || col.field, fields: next });
                                  }}
                                />
                                <span>{opt.label}</span>
                              </label>
                            );
                          })}
                        </div>
                      </div>
                      {col.cells.length > 0 && (
                        <ul>
                          {col.cells.slice(0, 6).map((c, i) => (
                            <li key={i}>{c.text}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        <div className="ann-subhead">
          <span>页内单值信息（卡号 / 户名 / 开户行）</span>
          <button type="button" className="ann-link-btn" onClick={onStartDrawSingle}>
            + 框单值
          </button>
        </div>
        {singles.length === 0 ? (
          <div className="ann-empty-hint">未检测到单值信息，可点「+ 框单值」手动框选卡号或户名。</div>
        ) : (
          <div className="ann-single-list">
            {singles.map((s) => {
              const isSel = selected?.kind === 'single' && selected.id === s.id;
              return (
                <div
                  key={s.id}
                  className={`ann-single-item ${isSel ? 'selected' : ''}`}
                  onClick={() => onSelect({ kind: 'single', id: s.id })}
                >
                  <select
                    value={s.field}
                    onChange={(e) => {
                      const opt = singleOptions.find((o) => o.key === e.target.value);
                      onUpdateSingle(s.id, { field: e.target.value, label: opt?.label || e.target.value });
                    }}
                  >
                    {singleOptions.map((opt) => (
                      <option key={opt.key} value={opt.key}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                  <span className="ann-single-val" title={s.value}>
                    {s.value || '（手动框区域）'}
                  </span>
                  {isSel && (
                    <div className="small muted" style={{ display: 'flex', gap: 4, marginTop: 4, width: '100%', flexWrap: 'wrap' }} onClick={(e) => e.stopPropagation()}>
                      {(['x', 'y', 'w', 'h'] as const).map((k) => (
                        <label key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 2, fontSize: 11 }}>
                          {k.toUpperCase()}%
                          <input
                            type="number"
                            step="0.5"
                            min="0"
                            max="100"
                            style={{ width: 52, padding: '1px 3px', fontSize: 11 }}
                            value={Number((s[k] * 100).toFixed(1))}
                            onChange={(e) => {
                              const v = Math.max(0, Math.min(1, Number(e.target.value) / 100));
                              if (Number.isFinite(v)) onUpdateSingle(s.id, { [k]: v });
                            }}
                          />
                        </label>
                      ))}
                    </div>
                  )}
                  <button
                    type="button"
                    className="ann-mini-btn danger"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteSingle(s.id);
                    }}
                  >
                    ×
                  </button>
                </div>
              );
            })}
          </div>
        )}

        <div className="ann-subhead">
          <span>必需字段（缺列时试跑与报告会提示）</span>
        </div>
        <div className="ann-req-chips">
          {['txn_date', 'amount', 'balance', 'summary', 'counterparty_name'].map((key) => (
            <label key={key} className="ann-req-chip">
              <input
                type="checkbox"
                checked={requiredFields.includes(key)}
                onChange={() => onToggleRequired(key)}
              />
              <span>{fieldLabel(key, customFields)}</span>
            </label>
          ))}
        </div>
      </section>

      <section className="ann-step ann-save-step">
        <div className="ann-step-head">
          <span className="ann-step-num">4</span>
          <strong>试跑与交付</strong>
        </div>
        <div className="ann-action-stack">
          <Button variant="secondary" onClick={onDryRun} disabled={busy || columns.length === 0}>
            立即试跑预览（验证实际解析结果）
          </Button>
          {editingTaskId && onReparseTask && (
            <Button onClick={onReparseTask} disabled={busy || columns.length === 0}>
              仅用于任务 #{editingTaskId} 重解析
            </Button>
          )}
          {validationIssues.length > 0 && (
            <div style={{ border: '1px solid #f59e0b', background: '#fffbeb', borderRadius: 6, padding: 8, fontSize: 12 }}>
              <strong style={{ display: 'block', marginBottom: 4 }}>保存前实时核对（{validationIssues.length}）</strong>
              {validationIssues.map((iss, idx) => (
                <div
                  key={idx}
                  style={{
                    color: iss.level === 'error' ? '#b91c1c' : '#92400e',
                    cursor: iss.target ? 'pointer' : 'default',
                    marginBottom: 2,
                  }}
                  onClick={() => iss.target && onSelect(iss.target)}
                >
                  [{iss.code}] {iss.message}
                </div>
              ))}
            </div>
          )}
          <label className="ann-field" style={{ display: 'block' }}>
            <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>这份流水属于哪家银行（必填，保存时写入模板）</span>
            {customBankMode ? (
              <input
                className="ann-input"
                style={{ width: '100%', marginTop: 4 }}
                placeholder="输入银行编码（如 BOB / HXB）"
                value={bankCode}
                onChange={(e) => onBankCodeChange(e.target.value.toUpperCase())}
              />
            ) : (
              <select
                className="ann-input"
                style={{ width: '100%', marginTop: 4 }}
                value={BANK_OPTIONS.some((b) => b.code === bankCode) ? bankCode : ''}
                onChange={(e) => onBankCodeChange(e.target.value)}
              >
                <option value="">请选择银行</option>
                {BANK_OPTIONS.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.label}（{item.code}）
                  </option>
                ))}
              </select>
            )}
          </label>
          <div className="ann-save-pair">
            <Button
              variant={isAdmin ? 'primary' : 'secondary'}
              onClick={() => onSaveTemplate(isAdmin)}
              disabled={busy || columns.length === 0}
            >
              {isAdmin ? '保存并立即启用' : '保存为草稿'}
            </Button>
            {isAdmin && (
              <Button
                variant="secondary"
                onClick={() => onSaveTemplate(false)}
                disabled={busy || columns.length === 0}
              >
                仅存草稿
              </Button>
            )}
          </div>
        </div>
      </section>
    </aside>
  );
}
