import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  analyzeTemplateFields,
  deleteTemplate,
  disableTemplate,
  duplicateTemplate,
  exportTemplateBlob,
  importTemplate,
  listTemplates,
  loadBuiltinTemplates,
  publishTemplate,
  restoreTemplate,
  type HeaderFieldSpec,
  type ShortFieldSpec,
  type TemplateAnalyzeResult,
  type TemplateRow,
} from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { getUser } from '../../auth/store';
import {
  bankLabel,
  BOX_COLORS,
  buildBoxesFromAnalyzeResult,
  DEFAULT_HEADER_FIELDS,
  DEFAULT_SHORT_FIELDS,
} from '../../components/annotate/types';
import { PdfPageCanvas } from '../../components/PdfPageCanvas';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';

type Tab = 'active' | 'draft' | 'disabled' | 'trash';

const METHOD_LABEL: Record<string, string> = {
  inline: '同行粘连',
  right_neighbor: '右侧就近',
  below_neighbor: '下方就近',
};

function statusLabel(row: TemplateRow) {
  if (row.deleted_at) return '已删除';
  if (row.status === 'enabled') return '在用';
  if (row.status === 'draft') return '草稿';
  if (row.status === 'disabled') return '停用';
  return row.status;
}

export default function TemplatesPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const isAdmin = Boolean(getUser()?.is_admin);
  const [rows, setRows] = useState<TemplateRow[]>([]);
  const initTab = searchParams.get('tab');
  const [tab, setTab] = useState<Tab>(
    initTab === 'draft' || initTab === 'disabled' || initTab === 'trash' ? initTab : 'active',
  );
  const [search, setSearch] = useState('');
  const [bankFilter, setBankFilter] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState<number | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState('');
  const [importPublish, setImportPublish] = useState(false);
  const [builtinBusy, setBuiltinBusy] = useState(false);

  // 智能字段分析建模板面板状态
  const [analyzeOpen, setAnalyzeOpen] = useState(false);
  const [analyzeFile, setAnalyzeFile] = useState<File | null>(null);
  const [analyzeFileBytes, setAnalyzeFileBytes] = useState<ArrayBuffer | null>(null);
  const [analyzeBankCode, setAnalyzeBankCode] = useState('');
  const [analyzePassword, setAnalyzePassword] = useState('');
  const [shortFields, setShortFields] = useState<ShortFieldSpec[]>(() =>
    DEFAULT_SHORT_FIELDS.map((item) => ({ ...item })),
  );
  const [headerFields, setHeaderFields] = useState<HeaderFieldSpec[]>(() =>
    DEFAULT_HEADER_FIELDS.map((item) => ({ ...item })),
  );
  const [analyzeBusy, setAnalyzeBusy] = useState(false);
  const [analyzeResult, setAnalyzeResult] = useState<TemplateAnalyzeResult | null>(null);
  const [lastSavedTemplateId, setLastSavedTemplateId] = useState<number | null>(null);

  const load = (autoSwitchTab = false) => {
    listTemplates(true)
      .then((list) => {
        setRows(list);
        if (autoSwitchTab) {
          const hasActive = list.some((r) => !r.deleted_at && r.status === 'enabled');
          const hasDraft = list.some((r) => !r.deleted_at && r.status === 'draft');
          if (!hasActive && hasDraft) setTab('draft');
        }
      })
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  };

  useEffect(() => {
    load(true);
  }, []);

  const counts = {
    active: rows.filter((r) => !r.deleted_at && r.status === 'enabled').length,
    draft: rows.filter((r) => !r.deleted_at && r.status === 'draft').length,
    disabled: rows.filter((r) => !r.deleted_at && r.status === 'disabled').length,
    trash: rows.filter((r) => Boolean(r.deleted_at)).length,
  };

  const banks = Array.from(new Set(rows.map((r) => r.bank_code))).sort();


  const shown = rows.filter((row) => {
    if (tab === 'trash') {
      if (!row.deleted_at) return false;
    } else {
      if (row.deleted_at) return false;
      if (tab === 'active' && row.status !== 'enabled') return false;
      if (tab === 'draft' && row.status !== 'draft') return false;
      if (tab === 'disabled' && row.status !== 'disabled') return false;
    }
    if (bankFilter && row.bank_code !== bankFilter) return false;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      const hit =
        String(row.id).includes(q) ||
        row.bank_code.toLowerCase().includes(q) ||
        bankLabel(row.bank_code).toLowerCase().includes(q);
      if (!hit) return false;
    }
    return true;
  });

  async function act(id: number, action: () => Promise<unknown>, okMsg?: string) {
    setBusy(id);
    setError('');
    setNotice('');
    try {
      await action();
      if (okMsg) setNotice(okMsg);
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(null);
    }
  }

  async function onExport(row: TemplateRow) {
    try {
      const blob = await exportTemplateBlob(row.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `template-${row.bank_code}-v${row.version}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    }
  }

  async function onImportSubmit() {
    if (!importText.trim()) {
      setError('请先选择 .json 模板文件或粘贴模板 JSON 内容。');
      return;
    }
    setError('');
    setNotice('');
    let parsed: Record<string, unknown> | Record<string, unknown>[];
    try {
      parsed = JSON.parse(importText) as Record<string, unknown> | Record<string, unknown>[];
    } catch (err) {
      setError('JSON 格式不合法：' + ((err as Error).message || '请检查括号与引号'));
      return;
    }
    try {
      const payload =
        Array.isArray(parsed)
          ? { templates: parsed, publish: isAdmin && importPublish }
          : { ...parsed, publish: isAdmin && importPublish };
      const res = await importTemplate(payload);
      setImportOpen(false);
      setImportText('');
      const targetTab = res.status === 'enabled' ? 'active' : 'draft';
      setTab(targetTab);
      const cnt = res.count ?? 1;
      setNotice(
        cnt > 1
          ? `已批量导入 ${cnt} 个模板（已切到「${targetTab === 'active' ? '在用' : '草稿'}」页签）。`
          : `已导入模板 #${res.id}（${res.bank_code} v${res.version}，${res.status === 'enabled' ? '已启用' : '草稿状态'}）。`,
      );
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    }
  }

  async function onLoadBuiltin(force = false) {
    setBuiltinBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await loadBuiltinTemplates(isAdmin, force);
      if (res.loaded.length === 0) {
        setNotice(
          `内置标准模板（${res.skipped.join('、') || '工行/招行/建行/农行/中行/广发'}）均已有在用或草稿版本；如需刷新覆盖旧版可点「重装内置模板」。`,
        );
      } else {
        const targetTab = res.loaded.some((x) => x.status === 'enabled') ? 'active' : 'draft';
        setTab(targetTab);
        setNotice(`已载入 ${res.loaded.length} 份内置模板：${res.loaded.map((x) => `${x.bank_code} v${x.version}`).join('、')}。`);
      }
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBuiltinBusy(false);
    }
  }

  function updateShortField(index: number, key: keyof ShortFieldSpec, val: string) {
    setShortFields((prev) => prev.map((item, i) => (i === index ? { ...item, [key]: val } : item)));
  }

  function updateHeaderField(index: number, key: keyof HeaderFieldSpec, val: string) {
    setHeaderFields((prev) => prev.map((item, i) => (i === index ? { ...item, [key]: val } : item)));
  }

  async function onRunAnalyze(save = false, publish = false) {
    if (!analyzeFile) {
      setError('请先选择一份银行流水样例 PDF 文件。');
      return;
    }
    const cleanShort = shortFields.filter((f) => f.field.trim() && (f.label.trim() || f.keywords.trim()));
    const cleanHeader = headerFields.filter((f) => f.field.trim() && (f.label.trim() || f.keywords.trim()));
    if (cleanShort.length === 0 && cleanHeader.length === 0) {
      setError('请至少配置一个短字段或标题字段。');
      return;
    }
    setAnalyzeBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await analyzeTemplateFields({
        file: analyzeFile,
        shortFields: cleanShort,
        headerFields: cleanHeader,
        bankCode: analyzeBankCode,
        password: analyzePassword || undefined,
        save,
        publish: save && publish && isAdmin,
      });
      setAnalyzeResult(res);
      if (!analyzeBankCode && res.bank_code && res.bank_code !== 'UNKNOWN') {
        setAnalyzeBankCode(res.bank_code);
      }
      if (res.saved_template) {
        const st = res.saved_template;
        setLastSavedTemplateId(st.id);
        setTab(st.status === 'enabled' ? 'active' : 'draft');
        setNotice(
          `算法分析完成并已保存为模板 #${st.id}（${st.bank_code} v${st.version}，${st.status === 'enabled' ? '已启用' : '草稿'}）。`,
        );
        load();
      } else {
        const shortHit = res.short_results.filter((x) => x.matched).length;
        const headerHit = res.header_results.filter((x) => x.matched).length;
        setNotice(
          `分析完成：识别银行 ${res.bank_name || res.bank_code}，短字段命中 ${shortHit}/${res.short_results.length}，标题字段命中 ${headerHit}/${res.header_results.length}，试解析 ${res.preview_rows.length} 行。`,
        );
      }
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setAnalyzeBusy(false);
    }
  }

  const matchedHeaders = analyzeResult?.header_results.filter((h) => h.matched) ?? [];

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>模板库</h1>
          <p className="sub">模板决定特定银行版式的几何列框与单值抽取策略；支持字段智能分析建模板、画布微调、实时试跑与版本迭代，删除仅软入回收站。</p>
        </div>
        <div className="filters">
          <Button
            size="sm"
            onClick={() => {
              setAnalyzeOpen((v) => !v);
              setImportOpen(false);
            }}
          >
            {analyzeOpen ? '收起智能分析' : '智能字段分析建模板'}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => navigate('/bank/annotate')}>
            + 画布新建标注
          </Button>
          <Button size="sm" variant="ghost" disabled={builtinBusy} onClick={() => void onLoadBuiltin(false)}>
            {builtinBusy ? '载入中…' : '载入内置标准模板'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={builtinBusy}
            title="忽略已有版本强制生成新一版内置模板"
            onClick={() => void onLoadBuiltin(true)}
          >
            重装内置模板
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setImportOpen((v) => !v);
              setAnalyzeOpen(false);
            }}
          >
            导入模板 JSON
          </Button>
        </div>
      </header>

      <div className="filters-bar">
        <div className="tabs small-tabs">
          {([
            ['active', '在用'],
            ['draft', '草稿'],
            ['disabled', '已停用'],
            ['trash', '回收站'],
          ] as [Tab, string][]).map(([key, label]) => (
            <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>
              {label}（{counts[key]}）
            </button>
          ))}
        </div>
        <div className="filters">
          <select value={bankFilter} onChange={(e) => setBankFilter(e.target.value)} aria-label="按银行筛选">
            <option value="">全部银行</option>
            {banks.map((b) => (
              <option key={b} value={b}>{bankLabel(b)} ({b})</option>
            ))}
          </select>
          <input
            type="search"
            placeholder="搜编号 / 银行名称或代码"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="ok">{notice}</Notice> : null}

      {analyzeOpen && (
        <div className="import-box" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="import-box-head" style={{ flexWrap: 'wrap', gap: 10 }}>
            <div>
              <strong>智能字段分析建模板（短字段就近匹配 + 标题字段版式分析）</strong>
              <p className="small muted" style={{ margin: '4px 0 0' }}>
                上传银行流水样例 PDF 并填写需要解析的短字段与标题字段，后端自动定位页眉键值与明细列坐标，支持预览后一键入库。
              </p>
            </div>
            <div className="filters" style={{ flexWrap: 'wrap' }}>
              <input
                type="file"
                accept=".pdf,application/pdf,image/png,image/jpeg,image/webp"
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null;
                  setAnalyzeFile(f);
                  setAnalyzeResult(null);
                  setLastSavedTemplateId(null);
                  if (f) {
                    f.arrayBuffer().then(setAnalyzeFileBytes).catch(() => setAnalyzeFileBytes(null));
                  } else {
                    setAnalyzeFileBytes(null);
                  }
                }}
              />
              <input
                type="text"
                style={{ width: 130 }}
                placeholder="银行代码（自动识别）"
                value={analyzeBankCode}
                onChange={(e) => setAnalyzeBankCode(e.target.value.toUpperCase())}
              />
              <input
                type="password"
                style={{ width: 130 }}
                placeholder="PDF 口令（可选）"
                value={analyzePassword}
                onChange={(e) => setAnalyzePassword(e.target.value)}
              />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: 14 }}>
            {/* 短字段配置 */}
            <div style={{ border: '1px solid var(--border, #d8dee9)', borderRadius: 8, padding: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div>
                  <strong>1. 短字段（就近匹配）</strong>
                  <span className="small muted" style={{ marginLeft: 8 }}>页眉单值：同行粘连 / 右侧就近 / 下方就近</span>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    setShortFields((prev) => [
                      ...prev,
                      { field: `short_${prev.length + 1}`, label: '', keywords: '' },
                    ])
                  }
                >
                  + 添加短字段
                </Button>
              </div>
              <table className="grid" style={{ margin: 0 }}>
                <thead>
                  <tr><th style={{ width: 115 }}>字段键</th><th style={{ width: 95 }}>显示名</th><th>匹配锚点词（逗号分隔）</th><th style={{ width: 46 }}>删</th></tr>
                </thead>
                <tbody>
                  {shortFields.map((sf, idx) => (
                    <tr key={idx}>
                      <td>
                        <input
                          style={{ width: '100%' }}
                          value={sf.field}
                          onChange={(e) => updateShortField(idx, 'field', e.target.value)}
                          placeholder="account_no"
                        />
                      </td>
                      <td>
                        <input
                          style={{ width: '100%' }}
                          value={sf.label}
                          onChange={(e) => updateShortField(idx, 'label', e.target.value)}
                          placeholder="卡号/账号"
                        />
                      </td>
                      <td>
                        <input
                          style={{ width: '100%' }}
                          value={sf.keywords}
                          onChange={(e) => updateShortField(idx, 'keywords', e.target.value)}
                          placeholder="卡号,账号,客户账号"
                        />
                      </td>
                      <td>
                        <button
                          className="link-btn danger"
                          onClick={() => setShortFields((prev) => prev.filter((_, i) => i !== idx))}
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* 标题字段配置 */}
            <div style={{ border: '1px solid var(--border, #d8dee9)', borderRadius: 8, padding: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div>
                  <strong>2. 标题字段（版式分析）</strong>
                  <span className="small muted" style={{ marginLeft: 8 }}>明细表列：表头定位 + 间隙切分 + 行投影</span>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    setHeaderFields((prev) => [
                      ...prev,
                      { field: `col_${prev.length + 1}`, label: '', keywords: '' },
                    ])
                  }
                >
                  + 添加标题字段
                </Button>
              </div>
              <table className="grid" style={{ margin: 0 }}>
                <thead>
                  <tr><th style={{ width: 115 }}>字段键</th><th style={{ width: 95 }}>显示名</th><th>表头关键词（逗号分隔）</th><th style={{ width: 46 }}>删</th></tr>
                </thead>
                <tbody>
                  {headerFields.map((hf, idx) => (
                    <tr key={idx}>
                      <td>
                        <input
                          style={{ width: '100%' }}
                          value={hf.field}
                          onChange={(e) => updateHeaderField(idx, 'field', e.target.value)}
                          placeholder="txn_date"
                        />
                      </td>
                      <td>
                        <input
                          style={{ width: '100%' }}
                          value={hf.label}
                          onChange={(e) => updateHeaderField(idx, 'label', e.target.value)}
                          placeholder="交易日期"
                        />
                      </td>
                      <td>
                        <input
                          style={{ width: '100%' }}
                          value={hf.keywords}
                          onChange={(e) => updateHeaderField(idx, 'keywords', e.target.value)}
                          placeholder="交易日期,记账日期,日期"
                        />
                      </td>
                      <td>
                        <button
                          className="link-btn danger"
                          onClick={() => setHeaderFields((prev) => prev.filter((_, i) => i !== idx))}
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="actions" style={{ alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <Button size="sm" disabled={analyzeBusy} onClick={() => void onRunAnalyze(false, false)}>
              {analyzeBusy ? '算法分析中…' : '运行模板分析算法'}
            </Button>
            {analyzeResult && Object.keys(analyzeResult.field_map || {}).length > 0 && (
              <>
                <Button size="sm" variant="ghost" disabled={analyzeBusy} onClick={() => void onRunAnalyze(true, false)}>
                  保存为草稿模板
                </Button>
                {isAdmin && (
                  <Button size="sm" variant="ghost" disabled={analyzeBusy} onClick={() => void onRunAnalyze(true, true)}>
                    保存并直接启用
                  </Button>
                )}
              </>
            )}
            {lastSavedTemplateId && (
              <Button size="sm" variant="ghost" onClick={() => navigate('/bank/annotate?templateId=' + lastSavedTemplateId)}>
                去画布微调模板 #{lastSavedTemplateId}
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setShortFields(DEFAULT_SHORT_FIELDS.map((x) => ({ ...x })));
                setHeaderFields(DEFAULT_HEADER_FIELDS.map((x) => ({ ...x })));
              }}
            >
              重置默认字段
            </Button>
          </div>

          {analyzeResult && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, borderTop: '1px solid var(--border, #d8dee9)', paddingTop: 12 }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
                <span className="pill ok">
                  银行：{analyzeResult.bank_name ? `${analyzeResult.bank_name} (${analyzeResult.bank_code})` : analyzeResult.bank_code}
                </span>
                <span className="pill">共 {analyzeResult.page_count} 页</span>
                <span className={analyzeResult.header_found ? 'pill ok' : 'pill warn'}>
                  {analyzeResult.header_found ? '已定位明细表头' : '未定位到明细表头'}
                </span>
                <span className="pill">
                  短字段命中 {analyzeResult.short_results.filter((x) => x.matched).length}/{analyzeResult.short_results.length}
                </span>
                <span className="pill">
                  标题字段命中 {matchedHeaders.length}/{analyzeResult.header_results.length}
                </span>
                <span className="pill">试解析预览 {analyzeResult.preview_rows.length} 行</span>
                {analyzeResult.engine && (
                  <span className="pill">{analyzeResult.ocr_used ? `OCR (${analyzeResult.engine})` : analyzeResult.engine}</span>
                )}
              </div>

              {analyzeFileBytes && (() => {
                const viz = buildBoxesFromAnalyzeResult(analyzeResult, shortFields, headerFields);
                const pageRegs = viz.regions.filter((r) => r.page === 0);
                const regIds = new Set(pageRegs.map((r) => r.id));
                const pageCols = viz.columns.filter((c) => regIds.has(c.regionId));
                const pageSingles = viz.singles.filter((s) => s.page === 0);
                const refReg = pageRegs[0];
                return (
                  <details open>
                    <summary className="small"><strong>版式框选可视化预览（首页叠框：青色短字段 + 紫色表格区 + 彩色列框）</strong></summary>
                    <div className="ann-stage-wrap" style={{ marginTop: 8, maxHeight: 540, overflow: 'auto' }}>
                      <PdfPageCanvas
                        fileBytes={analyzeFileBytes}
                        mimeHint={analyzeFile?.type || undefined}
                        pageIndex={0}
                        zoom={1.1}
                        password={analyzePassword || undefined}
                        overlay={
                          <div className="ann-overlay" style={{ pointerEvents: 'none' }}>
                            {pageRegs.map((r) => (
                              <div key={r.id}>
                                <div
                                  className="ann-area-box"
                                  style={{
                                    left: `${r.area.x * 100}%`,
                                    top: `${r.area.y * 100}%`,
                                    width: `${r.area.w * 100}%`,
                                    height: `${r.area.h * 100}%`,
                                  }}
                                />
                                <div
                                  className="ann-header-line"
                                  style={{ left: `${r.area.x * 100}%`, width: `${r.area.w * 100}%`, top: `${r.headerY * 100}%` }}
                                />
                              </div>
                            ))}
                            {pageCols.map((c, idx) => {
                              const color = BOX_COLORS[idx % BOX_COLORS.length];
                              return (
                                <div
                                  key={c.id}
                                  className="ann-col-box"
                                  style={{
                                    left: `${c.x * 100}%`,
                                    width: `${c.w * 100}%`,
                                    top: `${(refReg?.area.y ?? 0.16) * 100}%`,
                                    height: `${(refReg?.area.h ?? 0.72) * 100}%`,
                                    borderColor: color,
                                    background: `${color}1e`,
                                  }}
                                >
                                  <span className="ann-tag" style={{ background: color }}>
                                    {c.label || c.field}
                                  </span>
                                </div>
                              );
                            })}
                            {pageSingles.map((s) => (
                              <div
                                key={s.id}
                                className="ann-single-box"
                                style={{
                                  left: `${s.x * 100}%`,
                                  top: `${s.y * 100}%`,
                                  width: `${s.w * 100}%`,
                                  height: `${s.h * 100}%`,
                                }}
                              >
                                <span className="ann-tag single">{s.label}：{s.value}</span>
                              </div>
                            ))}
                          </div>
                        }
                      />
                    </div>
                  </details>
                );
              })()}

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: 12 }}>
                <div>
                  <strong className="small">短字段就近匹配结果</strong>
                  <table className="grid" style={{ marginTop: 6 }}>
                    <thead>
                      <tr><th>字段</th><th>状态</th><th>匹配方式</th><th>锚点词</th><th>提取值</th><th>归一化坐标</th></tr>
                    </thead>
                    <tbody>
                      {analyzeResult.short_results.map((item) => (
                        <tr key={item.field}>
                          <td>{item.label} <span className="small muted">({item.field})</span></td>
                          <td><span className={item.matched ? 'pill ok' : 'pill'}>{item.matched ? '命中' : '未命中'}</span></td>
                          <td className="small muted">{item.method ? (METHOD_LABEL[item.method] || item.method) : '—'}</td>
                          <td className="small muted">{item.anchor_text || '—'}</td>
                          <td><strong>{item.value || '—'}</strong></td>
                          <td className="small muted">
                            {item.rect
                              ? `${Math.round(item.rect.x * 100)}%, ${Math.round(item.rect.y * 100)}% (${Math.round(item.rect.w * 100)}%×${Math.round(item.rect.h * 100)}%)`
                              : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div>
                  <strong className="small">标题字段版式分析结果</strong>
                  <table className="grid" style={{ marginTop: 6 }}>
                    <thead>
                      <tr><th>字段</th><th>状态</th><th>命中表头</th><th>列位置 / 宽度</th><th>命中行</th><th>样例值</th></tr>
                    </thead>
                    <tbody>
                      {analyzeResult.header_results.map((item) => (
                        <tr key={item.field}>
                          <td>{item.label} <span className="small muted">({item.field})</span></td>
                          <td><span className={item.matched ? 'pill ok' : 'pill'}>{item.matched ? '命中' : '未命中'}</span></td>
                          <td><strong>{item.header_text || '—'}</strong></td>
                          <td className="small muted">
                            {item.x != null && item.w != null
                              ? `x=${(item.x * 100).toFixed(1)}% · w=${(item.w * 100).toFixed(1)}%`
                              : '—'}
                          </td>
                          <td className="small muted">{item.hit_rows}</td>
                          <td className="small muted">{item.sample_values.join(' / ') || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {analyzeResult.preview_rows.length > 0 && matchedHeaders.length > 0 && (
                <div>
                  <strong className="small">版式切分试解析预览（前 {analyzeResult.preview_rows.length} 行）</strong>
                  <div style={{ overflowX: 'auto', marginTop: 6 }}>
                    <table className="grid">
                      <thead>
                        <tr>
                          <th style={{ width: 44 }}>#</th>
                          {matchedHeaders.map((h) => (
                            <th key={h.field}>{h.label}（{h.header_text}）</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {analyzeResult.preview_rows.map((r, rIdx) => (
                          <tr key={rIdx}>
                            <td className="small muted">{rIdx + 1}</td>
                            {matchedHeaders.map((h) => (
                              <td key={h.field} className="small">{r.cells[h.field] || '—'}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {importOpen && (
        <div className="import-box">
          <div className="import-box-head">
            <strong>导入模板 JSON（粘贴导出文件或上传 .json）</strong>
            <input
              type="file"
              accept=".json,application/json"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) f.text().then(setImportText);
                e.target.value = '';
              }}
            />
          </div>
          <textarea
            rows={6}
            value={importText}
            placeholder='{"bank_code":"CCB","field_map":{"txn_date":"交易日期",...},"layout":{...}}'
            onChange={(e) => setImportText(e.target.value)}
          />
          <div className="actions" style={{ alignItems: 'center' }}>
            {isAdmin && (
              <label className="inline-check" style={{ marginRight: 10 }}>
                <input type="checkbox" checked={importPublish} onChange={(e) => setImportPublish(e.target.checked)} />
                导入后直接启用
              </label>
            )}
            <Button size="sm" onClick={() => void onImportSubmit()}>
              {isAdmin && importPublish ? '确认导入并启用' : '确认导入为草稿'}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setImportOpen(false)}>取消</Button>
          </div>
        </div>
      )}

      <table className="grid">
        <thead>
          <tr><th>编号</th><th>银行</th><th>版本</th><th>状态</th><th>框选与样本</th><th>使用统计</th><th>字段</th><th>更新时间</th><th>操作</th></tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr key={row.id}>
              <td>#{row.id}</td>
              <td>{bankLabel(row.bank_code)} <span className="small muted">{row.bank_code}</span></td>
              <td>v{row.version}</td>
              <td><span className={'pill ' + (row.status === 'enabled' ? 'ok' : row.status === 'draft' ? 'warn' : '')}>{statusLabel(row)}</span></td>
              <td className="small">
                <span className={row.has_layout ? 'pill ok' : 'pill'}>{row.has_layout ? '有框选布局' : '仅列映射'}</span>
                {' '}
                {row.has_sample && <span className="pill ok">含样本</span>}
              </td>
              <td className="small muted">
                {row.tasks_total ? `${row.tasks_total} 次 · ${Math.round((row.success_rate ?? 0) * 100)}%` : '暂无'}
              </td>
              <td className="small muted">{Object.keys(row.field_map ?? {}).length} 项</td>
              <td className="small muted">{row.updated_at ? new Date(row.updated_at).toLocaleString() : '—'}</td>
              <td className="small actions-cell">
                <Link className="link-btn" to={'/bank/templates/' + row.id}>详情</Link>
                <button className="link-btn" onClick={() => navigate('/bank/annotate?templateId=' + row.id)}>
                  画布编辑
                </button>
                <button className="link-btn" onClick={() => navigate('/bank/templates/' + row.id + '/layout')}>
                  版式图
                </button>
                <button className="link-btn" onClick={() => void onExport(row)}>
                  导出
                </button>
                {row.deleted_at ? (
                  isAdmin ? (
                    <button className="link-btn" disabled={busy === row.id} onClick={() => void act(row.id, () => restoreTemplate(row.id), `已恢复模板 #${row.id}`)}>
                      恢复
                    </button>
                  ) : null
                ) : (
                  <>
                    {isAdmin && row.status !== 'enabled' ? (
                      <button className="link-btn" disabled={busy === row.id} onClick={() => void act(row.id, () => publishTemplate(row.id), `已启用模板 #${row.id}`)}>
                        启用
                      </button>
                    ) : null}
                    {isAdmin && row.status === 'enabled' ? (
                      <button className="link-btn" disabled={busy === row.id} onClick={() => void act(row.id, () => disableTemplate(row.id), `已停用模板 #${row.id}`)}>
                        停用
                      </button>
                    ) : null}
                    {isAdmin ? (
                      <button className="link-btn" disabled={busy === row.id} onClick={() => void act(row.id, () => duplicateTemplate(row.id), `已复制模板 #${row.id} 为新草稿`)}>
                        复制
                      </button>
                    ) : null}
                    {isAdmin ? (
                      <button
                        className="link-btn danger"
                        disabled={busy === row.id}
                        onClick={() => void act(row.id, () => deleteTemplate(row.id), `模板 #${row.id} 已移入回收站`)}
                      >
                        移入回收站
                      </button>
                    ) : null}
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {shown.length === 0 ? (
        <div className="empty-guide">
          <p className="muted">
            {counts.active || counts.draft || counts.disabled
              ? '这一栏没有模板，但库里有 ' +
                [
                  counts.active ? counts.active + ' 份在用' : '',
                  counts.draft ? counts.draft + ' 份草稿' : '',
                  counts.disabled ? counts.disabled + ' 份已停用' : '',
                  counts.trash ? counts.trash + ' 份在回收站' : '',
                ].filter(Boolean).join('、') + '。'
              : '库里还没有任何模板。'}
          </p>
          <div className="empty-actions">
            {counts.draft ? <button className="btn btn-ghost" onClick={() => setTab('draft')}>去看草稿（{counts.draft}）</button> : null}
            {counts.disabled ? <button className="btn btn-ghost" onClick={() => setTab('disabled')}>去看已停用（{counts.disabled}）</button> : null}
            <button className="btn" onClick={() => navigate('/bank/annotate')}>标注一份新模板</button>
            <button className="btn btn-ghost" onClick={() => setImportOpen(true)}>导入 JSON</button>
          </div>
          <p className="muted small">
            模板只有「在用」才会被解析采用：新标注保存后是草稿，点「启用」才生效。
          </p>
        </div>
      ) : null}
    </div>
  );
}
