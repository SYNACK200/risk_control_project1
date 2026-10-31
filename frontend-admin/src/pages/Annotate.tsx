import { useEffect, useMemo, useState } from 'react';
import { Toolbar } from '../components/Toolbar';
import { Stage } from '../components/Stage';
import { Inspector } from '../components/Inspector';
import { ValidationPanel } from '../components/ValidationPanel';
import {
  clearDraft, createEmpty, downloadText, hasBlockingError,
  loadDraft, saveDraft, serialize, uid, validate,
} from '../lib/template';
import { PdfPasswordError, openSampleFile } from '../lib/pdf';
import { ArchiveError, extractStatement, isArchive } from '../lib/archive';
import { PasswordDialog, type PasswordRequest } from '../components/PasswordDialog';
import { createDemoPage } from '../lib/sample';
import { inferTemplate, type InferResult } from '../lib/api';
import type { FieldMapV1, Issue, Rect, SamplePage, Selection, Tool } from '../lib/types';

type Notice = { level: 'info' | 'error' | 'warning'; text: string } | null;
type SpecialLevel = 'info' | 'warn' | 'error';
interface SpecialEvent { time: string; name: string; stage: string; result: string; level: SpecialLevel }
interface Pending { file: File; kind: 'zip' | 'pdf'; target: string; attempts: number; wrong: boolean }
const MAX_PW_ATTEMPTS = 3;
const SOURCE_LABEL: Record<string, string> = { labeled: '人工标注', inferred: '统计推断', derived: '派生' };

/** 标注比例 × 页面尺寸即 PDF pt（SamplePage 取自 viewport scale=1），与后端 pdfplumber 坐标一致。 */
function toPoint(value: number, total: number) {
  return Math.round(value * total * 10) / 10;
}

function marksFromMap(map: FieldMapV1): { field: string; page: number; x: number; y: number }[] {
  const marks: { field: string; page: number; x: number; y: number }[] = [];
  const seen = new Set<string>();
  for (const table of map.tables) {
    for (const col of table.columns) {
      if (!col.field || seen.has(col.field)) continue;
      seen.add(col.field);
      marks.push({
        field: col.field,
        page: Math.max(0, table.page - 1),
        x: toPoint(col.x + col.w / 2, map.page_size.w),
        y: toPoint(table.headerY ?? table.area.y + 0.01, map.page_size.h),
      });
    }
  }
  if (marks.length > 0) return marks;
  for (const box of map.meta_boxes) {
    if (!box.field || seen.has(box.field)) continue;
    seen.add(box.field);
    marks.push({
      field: box.field,
      page: Math.max(0, box.page - 1),
      x: toPoint(box.rect.x + box.rect.w / 2, map.page_size.w),
      y: toPoint(box.rect.y + box.rect.h / 2, map.page_size.h),
    });
  }
  return marks;
}

export function AnnotatePage() {
  const [map, setMap] = useState<FieldMapV1>(() => loadDraft() ?? createEmpty());
  const [sample, setSample] = useState<SamplePage | null>(null);
  const [sampleName, setSampleName] = useState('');
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [tool, setTool] = useState<Tool>('meta');
  const [sel, setSel] = useState<Selection>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [source, setSource] = useState<{ file: File; password?: string } | null>(null);
  const [inference, setInference] = useState<InferResult | null>(null);
  const [inferring, setInferring] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [events, setEvents] = useState<SpecialEvent[]>([]);

  const pageCount = sample?.pageCount ?? 1;
  const issues: Issue[] = useMemo(() => validate(map, pageCount), [map, pageCount]);
  const blocking = issues.filter(i => i.level === 'error').length;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const res = saveDraft(map);
      if (!res.ok) setNotice({ level: 'warning', text: res.message ?? '草稿保存失败' });
    }, 600);
    return () => window.clearTimeout(timer);
  }, [map]);

  useEffect(() => {
    const current = sample;
    return () => { current?.dispose(); };
  }, [sample]);

  useEffect(() => {
    setInference(null);
  }, [map]);

  function hint(text: string) { setNotice({ level: 'info', text }); }

  function logEvent(name: string, stage: string, result: string, level: SpecialLevel) {
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    setEvents(prev => [{ time, name, stage, result, level }, ...prev].slice(0, 12));
  }

  async function openPage(file: File, password?: string) {
    const opened = await openSampleFile(file, password);
    setSample(opened);
    setSampleName(file.name);
    setSource({ file, password });
    setInference(null);
    setPage(1);
    setSel(null);
    setMap(prev => ({
      ...prev,
      page_size: { w: Math.round(opened.width * 100) / 100, h: Math.round(opened.height * 100) / 100 },
      meta: { ...prev.meta, sample_name: file.name },
    }));
    setNotice({ level: 'info', text: `已载入 ${file.name}（${opened.pageCount} 页）。样例在本机读取；点“试解析”时才会上传到本机后端。` });
    logEvent(file.name, '打开材料', `${opened.pageCount} 页，可标注`, 'info');
  }

  /** 收件：压缩包先解开（可能要口令），再按 PDF/图片打开。 */
  async function loadFile(file: File) {
    logEvent(file.name, '收到材料', `${(file.size / 1024).toFixed(1)} KB`, 'info');
    if (isArchive(file)) {
      try {
        const result = await extractStatement(file);
        if (result.status === 'need-password') {
          logEvent(file.name, '识别为加密压缩包', '需要客户提供口令', 'warn');
          setPending({ file, kind: 'zip', target: result.name, attempts: 0, wrong: false });
          return;
        }
        if (result.status === 'wrong-password') {
          logEvent(file.name, '压缩包口令', '口令不正确', 'error');
          return;
        }
        logEvent(file.name, '压缩包已解开', result.others > 0 ? `取首个材料，另有 ${result.others} 份未受理` : '单份材料', 'info');
        const inner = new File([result.blob], result.name, { type: result.name.toLowerCase().endsWith('.pdf') ? 'application/pdf' : 'image/*' });
        await openPage(inner);
      } catch (err) {
        const msg = err instanceof ArchiveError ? err.message : err instanceof Error ? err.message : String(err);
        setNotice({ level: 'error', text: msg });
        logEvent(file.name, '压缩包处理', msg, 'error');
      }
      return;
    }
    try {
      await openPage(file);
    } catch (err) {
      if (err instanceof PdfPasswordError) {
        logEvent(file.name, 'PDF 需要口令', err.kind === 'needed' ? '等待输入' : '口令不正确', err.kind === 'needed' ? 'warn' : 'error');
        setPending(prev => prev
          ? { ...prev, file, kind: 'pdf', target: file.name, wrong: err.kind === 'wrong' }
          : { file, kind: 'pdf', target: file.name, attempts: 0, wrong: false });
        return;
      }
      const msg = err instanceof Error ? err.message : String(err);
      setNotice({ level: 'error', text: msg });
      logEvent(file.name, '打开材料', msg, 'error');
    }
  }

  async function submitPassword(password: string) {
    if (!pending) return;
    const attempts = pending.attempts + 1;
    if (pending.kind === 'zip') {
      try {
        const result = await extractStatement(pending.file, password);
        if (result.status === 'wrong-password') {
          logEvent(pending.target, `压缩包口令第 ${attempts} 次`, '口令不正确', 'error');
          if (attempts >= MAX_PW_ATTEMPTS) {
            setPending(null);
            setNotice({ level: 'error', text: '口令错误已达 3 次，已停止尝试。请让客户重新导出或告知口令后再提交。' });
            logEvent(pending.target, '放弃解包', '连续 3 次口令错误', 'error');
            return;
          }
          setPending({ ...pending, attempts, wrong: true });
          return;
        }
        if (result.status === 'ok') {
          setPending(null);
          logEvent(pending.target, '压缩包口令通过', `第 ${attempts} 次成功`, 'info');
          const inner = new File([result.blob], result.name, { type: result.name.toLowerCase().endsWith('.pdf') ? 'application/pdf' : 'image/*' });
          await openPage(inner);
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setNotice({ level: 'error', text: msg });
        logEvent(pending.target, '压缩包解包', msg, 'error');
        setPending(null);
      }
      return;
    }
    try {
      await openPage(pending.file, password);
      setPending(null);
      logEvent(pending.target, 'PDF 口令通过', `第 ${attempts} 次成功`, 'info');
    } catch (err) {
      if (err instanceof PdfPasswordError && err.kind === 'wrong') {
        logEvent(pending.target, `PDF 口令第 ${attempts} 次`, '口令不正确', 'error');
        if (attempts >= MAX_PW_ATTEMPTS) {
          setPending(null);
          setNotice({ level: 'error', text: '口令错误已达 3 次，已停止尝试。请让客户提供正确口令或改用去口令版本。' });
          return;
        }
        setPending({ ...pending, attempts, wrong: true });
        return;
      }
      const msg = err instanceof Error ? err.message : String(err);
      setNotice({ level: 'error', text: msg });
      logEvent(pending.target, '打开材料', msg, 'error');
      setPending(null);
    }
  }

  function cancelPassword() {
    if (pending) logEvent(pending.target, '取消输入口令', '本次不打开该材料', 'warn');
    setPending(null);
  }

  function loadDemo() {
    const demo = createDemoPage();
    setSample(demo);
    setSampleName('内置示例页（假数据）');
    setSource(null);
    setInference(null);
    setPage(1);
    setSel(null);
    setMap(prev => ({
      ...prev,
      page_size: { w: demo.width, h: demo.height },
      meta: { ...prev.meta, sample_name: 'demo.png' },
    }));
    setNotice({ level: 'info', text: '已载入内置示例页，可直接练习标注；示例页没有源文件，不能试解析。' });
  }

  function draw(rect: Rect) {
    if (!sample) { hint('先载入样例文件或点「示例页」'); return; }
    if (tool === 'meta') {
      const box = { id: uid('m'), field: '', page, rect };
      setMap(prev => ({ ...prev, meta_boxes: [...prev.meta_boxes, box] }));
      setSel({ kind: 'meta', id: box.id });
      hint('已画字段框，请在右侧选择它对应的字段。');
      return;
    }
    if (tool === 'table') {
      const table = { id: uid('t'), page, area: rect, columns: [] };
      setMap(prev => ({ ...prev, tables: [...prev.tables, table] }));
      setSel({ kind: 'table', id: table.id });
      hint('已画表格区。接着点「画列边界」，在区域内拖出每一列。');
      return;
    }
    const target = sel && (sel.kind === 'table' || sel.kind === 'column') ? sel : null;
    const tableId = target ? (target.kind === 'table' ? target.id : target.tableId) : '';
    const table = map.tables.find(t => t.id === tableId);
    if (!table) { hint('请先选中一个表格区，再画列'); return; }
    const x = Math.max(table.area.x, rect.x);
    const right = Math.min(table.area.x + table.area.w, rect.x + rect.w);
    if (right - x < 0.002) { hint('列宽太小或超出表格区，已忽略'); return; }
    const column = { field: '', x, w: Math.round((right - x) * 10000) / 10000 };
    setMap(prev => ({
      ...prev,
      tables: prev.tables.map(t => (t.id === table.id ? { ...t, columns: [...t.columns, column] } : t)),
    }));
    setSel({ kind: 'column', tableId: table.id, index: table.columns.length });
    hint('已加一列，请在右侧给它指定字段。');
  }

  function moveRect(kind: 'meta' | 'table', id: string, rect: Rect) {
    setMap(prev => {
      if (kind === 'meta') {
        return { ...prev, meta_boxes: prev.meta_boxes.map(b => (b.id === id ? { ...b, rect } : b)) };
      }
      return { ...prev, tables: prev.tables.map(t => (t.id === id ? { ...t, area: rect } : t)) };
    });
  }

  function removeSelected() {
    if (!sel) return;
    setMap(prev => {
      if (sel.kind === 'meta') return { ...prev, meta_boxes: prev.meta_boxes.filter(b => b.id !== sel.id) };
      if (sel.kind === 'table') return { ...prev, tables: prev.tables.filter(t => t.id !== sel.id) };
      return {
        ...prev,
        tables: prev.tables.map(t => (t.id === sel.tableId
          ? { ...t, columns: t.columns.filter((_, i) => i !== sel.index) }
          : t)),
      };
    });
    setSel(null);
  }

  function assign(field: string) {
    if (!sel) return;
    setMap(prev => {
      if (sel.kind === 'meta') {
        return { ...prev, meta_boxes: prev.meta_boxes.map(b => (b.id === sel.id ? { ...b, field } : b)) };
      }
      if (sel.kind === 'column') {
        return {
          ...prev,
          tables: prev.tables.map(t => (t.id === sel.tableId
            ? { ...t, columns: t.columns.map((c, i) => (i === sel.index ? { ...c, field } : c)) }
            : t)),
        };
      }
      return prev;
    });
  }

  function save() {
    if (blocking > 0) {
      setNotice({ level: 'error', text: `还有 ${blocking} 项错误未处理，先按右侧检查清单修完再保存。` });
      return;
    }
    const text = serialize(map);
    const safeBank = map.bank_code.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '') || 'template';
    downloadText(`field_map_${safeBank}.json`, text);
    const res = saveDraft(map);
    setNotice({
      level: res.ok ? 'info' : 'warning',
      text: res.ok
        ? '已导出 field_map JSON 并保存草稿。试解析结果仅供核对，保存模板请在模板管理里操作。'
        : `已导出 JSON，但草稿保存失败：${res.message ?? ''}`,
    });
  }

  function reset() {
    if (!window.confirm('清空所有标注？此操作不可撤销。')) return;
    clearDraft();
    setMap(createEmpty());
    setSel(null);
    setNotice({ level: 'info', text: '已清空标注。' });
  }

  async function runInfer() {
    if (!source) { hint('先载入一份 PDF 样例；内置示例页没有源文件，不能试解析。'); return; }
    if (!/\.pdf$/i.test(source.file.name) && source.file.type !== 'application/pdf') {
      hint('试解析目前只支持 PDF 电子件；图片件请先导出为 PDF。');
      return;
    }
    if (!map.page_size.w || !map.page_size.h) { hint('还没有记录样例页面尺寸，请重新载入样例。'); return; }
    const marks = marksFromMap(map);
    if (marks.length === 0) { hint('先给表格列指定字段，或画几个字段框，再试解析。'); return; }
    setInferring(true);
    setInference(null);
    setNotice({ level: 'info', text: `正在用 ${marks.length} 个标注外推…` });
    try {
      const form = new FormData();
      form.append('file', source.file);
      form.append('marks', JSON.stringify(marks));
      form.append('bank_code', map.bank_code || 'UNKNOWN');
      if (source.password) form.append('password', source.password);
      const res = await inferTemplate(form);
      setInference(res);
      const low = res.provenance.filter(r => r.confidence < 0.8).length;
      setNotice({
        level: res.warnings.length > 0 || low > 0 ? 'warning' : 'info',
        text: `试解析完成：识别 ${res.columns.length} 列，映射 ${Object.keys(res.field_map).length} 个字段${low > 0 ? `，${low} 个低置信` : ''}。`,
      });
      logEvent(sampleName, '试解析（列外推）', `${res.columns.length} 列 / ${res.provenance.length} 字段`, res.warnings.length > 0 ? 'warn' : 'info');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setNotice({ level: 'error', text: `试解析失败：${msg}` });
      logEvent(sampleName, '试解析（列外推）', msg, 'error');
    } finally {
      setInferring(false);
    }
  }

  return (
    <div className="app">
      <Toolbar
        tool={tool}
        onTool={setTool}
        page={page}
        pageCount={pageCount}
        onPage={p => { setPage(p); setSel(null); }}
        zoom={zoom}
        onZoom={setZoom}
        onFile={f => { void loadFile(f); }}
        onDemo={loadDemo}
        onSave={save}
        onReset={reset}
        blocking={blocking}
      />

      {notice && <div className={`notice ${notice.level}`}>{notice.text}</div>}

      <div className="toolbar2">
        <button className="btn" onClick={() => { void runInfer(); }} disabled={inferring}>
          {inferring ? '正在试解析…' : '用当前标注试解析'}
        </button>
        <span className="muted">
          {source ? '调用本机后端 /templates/infer，只做列外推；不保存模板、不生成报告。' : '先载入 PDF 样例（内置示例页不能试解析）'}
        </span>
      </div>

      {inference && (
        <section className="infer-panel">
          <div className="infer-head">
            <strong>试解析结果</strong>
            <span className="muted">识别 {inference.columns.length} 列 · 映射 {Object.keys(inference.field_map).length} 个字段</span>
            <button className="btn" onClick={() => setInference(null)}>关闭</button>
          </div>
          <div className="infer-grid">
            {/* 后端用 `p.column or 99` 排序，第 0 列会被排到最后，这里按列号重排 */}
            {[...inference.provenance].sort((a, b) => (a.column ?? 99) - (b.column ?? 99)).map(row => (
              <div className={`infer-row${row.confidence < 0.8 ? ' low' : ''}`} key={row.field}>
                <b>{row.field}</b>
                <span>{row.column === null ? '未匹配列' : `第 ${row.column + 1} 列`}</span>
                <span>{SOURCE_LABEL[row.source] ?? row.source}</span>
                <span>置信 {Math.round(row.confidence * 100)}%</span>
                <span className="muted">{row.why}</span>
              </div>
            ))}
          </div>
          {inference.warnings.length > 0 && <p className="infer-warn">告警：{inference.warnings.join('；')}</p>}
          {inference.columns.length > 0 && (
            <p className="muted">列样本：{inference.columns.map(c => `#${c.index + 1} ${c.samples.slice(0, 3).join(' / ') || '（空）'}`).join('；')}</p>
          )}
          <p className="muted">field_map：<span className="mono">{JSON.stringify(inference.field_map)}</span></p>
        </section>
      )}

      <div className="workspace">
        {sample ? (
          <Stage
            sample={sample}
            page={page}
            zoom={zoom}
            tool={tool}
            map={map}
            sel={sel}
            onDraw={draw}
            onSelect={setSel}
            onMove={moveRect}
            onHint={hint}
          />
        ) : (
          <div className="stage-wrap">
            <div className="empty">
              先载入一份样例流水（PDF / JPG / PNG），或点「示例页」用内置假数据练习。<br />
              样例在本机读取；点「试解析」时才会发往本机后端。
            </div>
          </div>
        )}

        <div className="side">
          <div className="side-scroll">
            <Inspector
              map={map}
              sel={sel}
              onBankCode={v => setMap(prev => ({ ...prev, bank_code: v }))}
              onKeywords={v => setMap(prev => ({ ...prev, match_rule: { ...prev.match_rule, bank_name_keywords: v } }))}
              onFingerprint={v => setMap(prev => ({ ...prev, match_rule: { ...prev.match_rule, header_fingerprint: v } }))}
              onAssign={assign}
              onHeaderY={y => setMap(prev => ({
                ...prev,
                tables: prev.tables.map(t => (sel?.kind === 'table' && t.id === sel.id ? { ...t, headerY: y } : t)),
              }))}
              onDelete={removeSelected}
              onAddCustom={f => setMap(prev => ({ ...prev, custom_fields: [...prev.custom_fields, f] }))}
              onRemoveCustom={code => setMap(prev => ({
                ...prev,
                custom_fields: prev.custom_fields.filter(c => c.code !== code),
                meta_boxes: prev.meta_boxes.map(b => (b.field === code ? { ...b, field: '' } : b)),
                tables: prev.tables.map(t => ({
                  ...t,
                  columns: t.columns.map(c => (c.field === code ? { ...c, field: '' } : c)),
                })),
              }))}
              onHint={hint}
            />
            <p className="muted" style={{ marginTop: 16 }}>
              试解析只做列外推：返回字段→列、来源和置信度，不会逐格回贴；逐笔抽取仍走报告链路。
            </p>
          </div>
          <section className="events">
            <div className="events-head">特殊情况检测</div>
            {events.length === 0 && <p className="muted small">还没有特殊情况。载入一份带口令的材料就会出现记录。</p>}
            <ul>
              {events.map((e, i) => (
                <li key={i} className={e.level}>
                  <span className="mono">{e.time}</span>
                  <b>{e.stage}</b>
                  <span className="muted">{e.result}</span>
                  <span className="ev-name">{e.name}</span>
                </li>
              ))}
            </ul>
          </section>

          <ValidationPanel
            issues={issues}
            onLocate={issue => {
              if (!issue.targetId) return;
              const asMeta = map.meta_boxes.find(b => b.id === issue.targetId);
              if (asMeta) { setSel({ kind: 'meta', id: asMeta.id }); setPage(asMeta.page); }
              const asTable = map.tables.find(t => t.id === issue.targetId);
              if (asTable) { setSel({ kind: 'table', id: asTable.id }); setPage(asTable.page); }
            }}
          />
        </div>
      </div>

      <div className="muted" style={{ padding: '6px 18px', background: '#fff', borderTop: '1px solid #e2e8f0' }}>
        样例：{sampleName || '未载入'} · 草稿自动保存在本机浏览器 · 试解析时文件与口令会发往本机后端
      </div>

      {pending && (
        <PasswordDialog
          request={{
            target: pending.target,
            kind: pending.kind,
            wrong: pending.wrong,
            attempts: pending.attempts,
            maxAttempts: MAX_PW_ATTEMPTS,
          } as PasswordRequest}
          onSubmit={pw => { void submitPassword(pw); }}
          onCancel={cancelPassword}
        />
      )}
    </div>
  );
}

export function hasIssues(map: FieldMapV1): boolean {
  return hasBlockingError(validate(map, 1));
}
