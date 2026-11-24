import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  analyzeTemplateFields,
  getTaskFile,
  getTemplate,
  getTemplateSample,
  listTasks,
  listTemplates,
  previewDraftTemplate,
  reparseTaskCanvas,
  saveTemplateFromCanvas,
  type HeaderFieldSpec,
  type ShortFieldSpec,
  type TaskSummary,
  type TemplatePreview,
  type TemplateRow,
} from '../../api/banker';
import {
  fetchSampleBytes,
  inspectFile,
  inspectSample,
  listSamples,
  spreadFile,
  spreadKeyword,
  type InspectPage,
  type InspectReport,
  type LabSample,
} from '../../api/lab';
import { getUser } from '../../auth/store';
import { AnnotateToolbar } from '../../components/annotate/AnnotateToolbar';
import { CanvasStage } from '../../components/annotate/CanvasStage';
import { PreviewDrawer } from '../../components/annotate/PreviewDrawer';
import { StepSidebar, type ValidationIssue } from '../../components/annotate/StepSidebar';
import {
  bankLabel,
  buildBoxesFromAnalyzeResult,
  buildBoxesFromInspectPage,
  buildTemplatePayload,
  DEFAULT_REQUIRED_FIELDS,
  fromSavedLayout,
  uid,
  type AnnotateSnapshot,
  type ColumnBox,
  type CustomFieldOption,
  type PageSlot,
  type SingleBox,
  type TableRegionBox,
  type ToolMode,
  BANK_OPTIONS,
} from '../../components/annotate/types';
import type { PageRenderSize } from '../../components/PdfPageCanvas';
import { extractStatement, isArchive } from '../../lib/archive';
import { Button } from '../../ui/Button';

type SourceState = {
  mode: 'sample' | 'file' | 'task' | 'template';
  label: string;
  sampleName?: string;
  blob: Blob | null;
  fileName: string;
  mimeHint?: string;
  bytes: ArrayBuffer | null;
};

function cloneSnapshot(s: AnnotateSnapshot): AnnotateSnapshot {
  return {
    regions: s.regions.map((r) => ({ ...r, area: { ...r.area } })),
    columns: s.columns.map((c) => ({ ...c, cells: [...c.cells], cellNorms: c.cellNorms ? [...c.cellNorms] : undefined })),
    singles: s.singles.map((m) => ({ ...m })),
  };
}

function guessMime(name: string, blobType?: string): string {
  if (blobType && blobType !== 'application/octet-stream') return blobType;
  const lower = name.toLowerCase();
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
  if (lower.endsWith('.webp')) return 'image/webp';
  return 'application/pdf';
}

function isPasswordError(msg: string): boolean {
  return /password|加密|密码|encrypted|decrypt/i.test(msg);
}

export function AnnotatePage() {
  const user = getUser();
  const isAdmin = user?.role === 'admin' || Boolean(user?.is_admin);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const queryTemplateId = searchParams.get('templateId') ? Number(searchParams.get('templateId')) : null;
  const queryTaskId = searchParams.get('taskId') ? Number(searchParams.get('taskId')) : null;

  const [samples, setSamples] = useState<LabSample[]>([]);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [templates, setTemplates] = useState<TemplateRow[]>([]);
  const [keepLayoutOnUpload, setKeepLayoutOnUpload] = useState(Boolean(queryTemplateId));
  const pendingZipRef = useRef<{ file: File; attempts: number } | null>(null);
  const [source, setSource] = useState<SourceState>({
    mode: 'sample',
    label: '',
    blob: null,
    fileName: 'sample.pdf',
    bytes: null,
  });

  const [editingTemplateId, setEditingTemplateId] = useState<number | null>(queryTemplateId);
  const [editingTaskId, setEditingTaskId] = useState<number | null>(queryTaskId);
  const [bankCode, setBankCode] = useState('');
  const [password, setPassword] = useState('');
  const [needPassword, setNeedPassword] = useState(false);

  const [inspectReport, setInspectReport] = useState<InspectReport | null>(null);
  const [pageCount, setPageCount] = useState(1);
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState<{ w: number; h: number }>({ w: 595, h: 842 });
  // 默认 1.6：800pt 的流水页在 1.1 倍下正文只有 8px 高，框线会把字盖住，看着像「框和字对不上」
  const [zoom, setZoom] = useState(1.6);
  const [tool, setTool] = useState<ToolMode>('select');
  const [showBoxes, setShowBoxes] = useState(true);
  const [focusWork, setFocusWork] = useState(false);

  const [regions, setRegions] = useState<TableRegionBox[]>([]);
  const [columns, setColumns] = useState<ColumnBox[]>([]);
  const [singles, setSingles] = useState<SingleBox[]>([]);
  const [customFields, setCustomFields] = useState<CustomFieldOption[]>([]);
  const [requiredFields, setRequiredFields] = useState<string[]>(DEFAULT_REQUIRED_FIELDS);

  const [activeRegionId, setActiveRegionId] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ kind: 'region' | 'col' | 'single'; id: string } | null>(null);
  const [keyword, setKeyword] = useState('');

  const [past, setPast] = useState<AnnotateSnapshot[]>([]);
  const [future, setFuture] = useState<AnnotateSnapshot[]>([]);
  const stateRef = useRef<AnnotateSnapshot>({ regions: [], columns: [], singles: [] });
  stateRef.current = { regions, columns, singles };

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [savedBanner, setSavedBanner] = useState<{ id: number; version: number; status: string } | null>(null);
  const [preview, setPreview] = useState<TemplatePreview | null>(null);

  const commitHistory = useCallback(() => {
    setPast((prev) => [...prev.slice(-29), cloneSnapshot(stateRef.current)]);
    setFuture([]);
  }, []);

  const handleUndo = useCallback(() => {
    setPast((prev) => {
      if (prev.length === 0) return prev;
      const target = prev[prev.length - 1];
      setFuture((f) => [cloneSnapshot(stateRef.current), ...f.slice(0, 29)]);
      setRegions(target.regions);
      setColumns(target.columns);
      setSingles(target.singles);
      setSelected(null);
      return prev.slice(0, -1);
    });
  }, []);

  const handleRedo = useCallback(() => {
    setFuture((prev) => {
      if (prev.length === 0) return prev;
      const [target, ...rest] = prev;
      setPast((p) => [...p.slice(-29), cloneSnapshot(stateRef.current)]);
      setRegions(target.regions);
      setColumns(target.columns);
      setSingles(target.singles);
      setSelected(null);
      return rest;
    });
  }, []);

  const applyInspectReport = useCallback(
    (report: InspectReport, keepExistingLayout: boolean) => {
      setInspectReport(report);
      const count = Math.max(1, report.page_count || report.pages.length || 1);
      setPageCount(count);
      if (report.pages[0]) {
        setPageSize({ w: Math.round(report.pages[0].width), h: Math.round(report.pages[0].height) });
      }
      if (keepExistingLayout) return;

      const allRegions: TableRegionBox[] = [];
      const allCols: ColumnBox[] = [];
      const allSingles: SingleBox[] = [];
      report.pages.forEach((p, idx) => {
        const built = buildBoxesFromInspectPage(p, idx);
        allRegions.push(...built.regions);
        allCols.push(...built.columns);
        allSingles.push(...built.singles);
      });
      if (allRegions.length === 0) {
        allRegions.push({
          id: uid('reg'),
          page: 0,
          slot: 'first',
          area: { x: 0.03, y: 0.16, w: 0.94, h: 0.76 },
          headerY: 0.16,
        });
      }
      setRegions(allRegions);
      setColumns(allCols);
      setSingles(allSingles);
      setActiveRegionId(allRegions[0]?.id ?? null);
      setSelected(null);
      setPast([]);
      setFuture([]);
    },
    [],
  );

  // Sync activeRegionId when switching pages
  useEffect(() => {
    const onThisPage = regions.filter((r) => r.page === pageIndex);
    if (onThisPage.length > 0 && !onThisPage.some((r) => r.id === activeRegionId)) {
      setActiveRegionId(onThisPage[0].id);
    }
  }, [pageIndex, regions, activeRegionId]);

  const loadSampleSource = useCallback(
    async (sampleName: string, keepLayout = false) => {
      setBusy(true);
      setError('');
      setNotice('');
      setNeedPassword(false);
      setPreview(null);
      try {
        const [bytes, report] = await Promise.all([fetchSampleBytes(sampleName), inspectSample(sampleName, 0)]);
        const mime = guessMime(sampleName);
        const blob = new Blob([bytes], { type: mime });
        setSource({
          mode: 'sample',
          label: sampleName,
          sampleName,
          blob,
          fileName: sampleName.split('/').pop() || 'sample.pdf',
          mimeHint: mime,
          bytes,
        });
        setPageIndex(0);
        applyInspectReport(report, keepLayout);
        // 内置样本文件名里带银行代码（clean/ccb.pdf）：没选银行时直接带出来，
        // 否则用户停在「请先选择银行」这一步，保存按钮点了没反应，看起来就是「存不了模板」。
        setBankCode((prev) => {
          if (prev) return prev;
          const base = (sampleName.split('/').pop() || '').toLowerCase().replace(/\.[a-z]+$/, '');
          const hit = BANK_OPTIONS.find((item) => item.code.toLowerCase() === base);
          return hit ? hit.code : prev;
        });
        setNotice(`已载入内置样本：${sampleName.split('/').pop()}（${report.ocr_used ? 'OCR 识字' : '文本层'}）`);
      } catch (e) {
        setError((e as Error).message || '载入内置样本失败');
      } finally {
        setBusy(false);
      }
    },
    [applyInspectReport],
  );

  const loadBlobSource = useCallback(
    async (
      blob: Blob,
      fileName: string,
      mode: 'file' | 'task' | 'template',
      label: string,
      pwd?: string,
      keepLayout = false,
      ocrPageIdx = 0,
    ) => {
      setBusy(true);
      setError('');
      setNotice('');
      setPreview(null);
      try {
        const bytes = await blob.arrayBuffer();
        const mime = guessMime(fileName, blob.type);
        const typedBlob = new Blob([bytes], { type: mime });
        setSource({ mode, label, blob: typedBlob, fileName, mimeHint: mime, bytes });
        const report = await inspectFile(typedBlob, pwd, ocrPageIdx, fileName);
        setNeedPassword(false);
        setPageIndex(ocrPageIdx);
        applyInspectReport(report, keepLayout);
        setNotice(
          report.ocr_used
            ? `已识字载入（OCR 第 ${ocrPageIdx + 1} 页，共 ${report.page_count} 页）`
            : `已识别文档结构（共 ${report.page_count} 页）`,
        );
      } catch (e) {
        const msg = (e as Error).message || '文件解析失败';
        if (isPasswordError(msg)) {
          setNeedPassword(true);
          setError('PDF 已加密，请在右侧输入打开密码后点击「重试识别」。');
        } else {
          setError(msg);
        }
      } finally {
        setBusy(false);
      }
    },
    [applyInspectReport],
  );

  const loadTemplateById = useCallback(
    async (tid: number) => {
      setBusy(true);
      setError('');
      setNotice('');
      setPreview(null);
      try {
        const tpl = await getTemplate(tid);
        setEditingTemplateId(tpl.id);
        setBankCode(tpl.bank_code || '');
        setRequiredFields(tpl.required_fields?.length ? tpl.required_fields : DEFAULT_REQUIRED_FIELDS);
        const loaded = fromSavedLayout(tpl.layout);
        setRegions(loaded.regions);
        setColumns(loaded.columns);
        setSingles(loaded.singles);
        setCustomFields(loaded.customFields);
        setActiveRegionId(loaded.regions[0]?.id ?? null);
        setKeepLayoutOnUpload(loaded.columns.length > 0 || loaded.singles.length > 0);
        setPast([]);
        setFuture([]);
        try {
          const sampleBlob = await getTemplateSample(tpl.id);
          const sampleName = sampleBlob.type.startsWith('image/') ? `template-${tpl.id}.png` : `template-${tpl.id}.pdf`;
          await loadBlobSource(sampleBlob, sampleName, 'template', `模板 #${tpl.id} 样本`, undefined, true, 0);
        } catch {
          setNotice(
            loaded.columns.length > 0
              ? `已载入模板 #${tpl.id}（${bankLabel(tpl.bank_code)} v${tpl.version}）的框选布局；暂无自带样本，在右侧上传流水 PDF 可保持框选直接预览。`
              : `已载入模板 #${tpl.id}（仅列映射，无几何框选）；请在右侧上传样例文件并框选或运行智能识别。`,
          );
          setBusy(false);
        }
      } catch (e) {
        setError((e as Error).message || '载入模板失败');
        setBusy(false);
      }
    },
    [loadBlobSource],
  );

  // Initial load: samples + recent tasks + template list + optional ?templateId= / ?taskId=
  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const [sRes, tRes, tplRes] = await Promise.all([
          listSamples().catch(() => ({ items: [] as LabSample[] })),
          listTasks({ limit: 30 }).catch(() => ({ items: [] as TaskSummary[] })),
          listTemplates(false).catch(() => [] as TemplateRow[]),
        ]);
        if (cancelled) return;
        setSamples(sRes.items || []);
        setTasks(tRes.items || []);
        setTemplates(tplRes || []);

        if (queryTemplateId) {
          await loadTemplateById(queryTemplateId);
          return;
        }

        if (queryTaskId) {
          setEditingTaskId(queryTaskId);
          const matchedTask = (tRes.items || []).find((t) => t.id === queryTaskId);
          if (matchedTask?.bank_code) setBankCode(matchedTask.bank_code);
          const taskBlob = await getTaskFile(queryTaskId);
          if (cancelled) return;
          const fileName =
            matchedTask?.carrier === 'IMAGE' || taskBlob.type.startsWith('image/')
              ? `task-${queryTaskId}.png`
              : `task-${queryTaskId}.pdf`;
          await loadBlobSource(taskBlob, fileName, 'task', `任务 #${queryTaskId}`, undefined, false, 0);
          return;
        }

        if ((sRes.items || []).length > 0) {
          await loadSampleSource(sRes.items[0].name, false);
        }
      } catch (e) {
        if (!cancelled) {
          setError((e as Error).message || '初始化画布失败');
          setBusy(false);
        }
      }
    }
    init();
    return () => {
      cancelled = true;
    };
  }, [queryTemplateId, queryTaskId, loadBlobSource, loadSampleSource, loadTemplateById]);

  // Keyboard shortcuts: Ctrl+Z / Ctrl+Y / Delete
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const inInput = target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName);
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        if (!inInput) {
          e.preventDefault();
          handleUndo();
        }
      } else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
        if (!inInput) {
          e.preventDefault();
          handleRedo();
        }
      } else if ((e.key === 'Delete' || e.key === 'Backspace') && !inInput && selected) {
        e.preventDefault();
        commitHistory();
        if (selected.kind === 'col') {
          setColumns((prev) => prev.filter((c) => c.id !== selected.id));
        } else if (selected.kind === 'single') {
          setSingles((prev) => prev.filter((s) => s.id !== selected.id));
        } else if (selected.kind === 'region') {
          setRegions((prev) => prev.filter((r) => r.id !== selected.id));
          setColumns((prev) => prev.filter((c) => c.regionId !== selected.id));
        }
        setSelected(null);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [handleUndo, handleRedo, selected, commitHistory]);

  const handleSelectTaskSource = async (tid: number) => {
    setEditingTaskId(tid);
    const matched = tasks.find((t) => t.id === tid);
    if (matched?.bank_code && !bankCode) setBankCode(matched.bank_code);
    setBusy(true);
    setError('');
    try {
      const blob = await getTaskFile(tid);
      const name = matched?.carrier === 'IMAGE' || blob.type.startsWith('image/') ? `task-${tid}.png` : `task-${tid}.pdf`;
      const preserve = keepLayoutOnUpload && (columns.length > 0 || singles.length > 0);
      await loadBlobSource(blob, name, 'task', `任务 #${tid}`, password || undefined, preserve, 0);
    } catch (e) {
      setError((e as Error).message || '读取任务原件失败');
      setBusy(false);
    }
  };

  const handleUploadFileSource = async (file: File, zipPwd?: string) => {
    pendingZipRef.current = null;
    if (isArchive(file)) {
      setBusy(true);
      setError('');
      setNotice('');
      try {
        const out = await extractStatement(file, zipPwd);
        if (out.status === 'need-password' || out.status === 'wrong-password') {
          const prevAttempts = zipPwd ? 1 : 0;
          pendingZipRef.current = { file, attempts: prevAttempts };
          setNeedPassword(true);
          setBusy(false);
          setError(
            out.status === 'wrong-password'
              ? `压缩包 ${out.name} 口令不正确，请在右侧重新输入解锁。`
              : `压缩包内文件 ${out.name} 已加密，请在右侧输入解压口令后点「解锁分析」。`,
          );
          return;
        }
        const preserve = keepLayoutOnUpload && (columns.length > 0 || singles.length > 0);
        await loadBlobSource(out.blob, out.name, 'file', `${file.name} › ${out.name}`, undefined, preserve, 0);
        return;
      } catch (e) {
        setError((e as Error).message || '读取 ZIP 压缩包失败');
        setBusy(false);
        return;
      }
    }
    const preserve = keepLayoutOnUpload && (columns.length > 0 || singles.length > 0);
    await loadBlobSource(file, file.name, 'file', file.name, password || undefined, preserve, 0);
  };

  const handleAnalyzeFieldsInCanvas = async (shortSpecs: ShortFieldSpec[], headerSpecs: HeaderFieldSpec[]) => {
    if (!source.blob) {
      setError('请先上传或载入一份样本文件，再执行智能识别。');
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await analyzeTemplateFields({
        file: source.blob,
        fileName: source.fileName,
        shortFields: shortSpecs,
        headerFields: headerSpecs,
        bankCode: bankCode || undefined,
        password: password || undefined,
        save: false,
      });
      commitHistory();
      const built = buildBoxesFromAnalyzeResult(res, shortSpecs, headerSpecs);
      if (built.regions.length > 0) setRegions(built.regions);
      setColumns(built.columns);
      setSingles(built.singles);
      setCustomFields(built.customFields);
      if (built.regions[0]) setActiveRegionId(built.regions[0].id);
      if (!bankCode && res.bank_code && res.bank_code !== 'UNKNOWN') setBankCode(res.bank_code);
      const sHit = res.short_results.filter((x) => x.matched).length;
      const hHit = res.header_results.filter((x) => x.matched).length;
      setNotice(
        `智能字段分析完成（${res.engine || 'layout'}）：短字段命中 ${sHit}/${res.short_results.length}，标题字段命中 ${hHit}/${res.header_results.length}，已自动更新画布框选。`,
      );
    } catch (e) {
      setError((e as Error).message || '智能字段分析失败');
    } finally {
      setBusy(false);
    }
  };

  const handleSwapAmountBalance = () => {
    const hasAmt = columns.some((c) => c.field === 'amount');
    const hasBal = columns.some((c) => c.field === 'balance');
    if (!hasAmt || !hasBal) return;
    commitHistory();
    setColumns((prev) =>
      prev.map((c) => {
        if (c.field === 'amount') return { ...c, field: 'balance', fields: ['balance'] };
        if (c.field === 'balance') return { ...c, field: 'amount', fields: ['amount'] };
        return c;
      }),
    );
    setNotice('已对调「交易金额」与「余额」列绑定，请重新点「立即试跑预览」验证。');
  };

  const handleReOcrPage = async () => {
    if (!source.blob && !source.sampleName) return;
    setBusy(true);
    setError('');
    try {
      const report =
        source.mode === 'sample' && source.sampleName
          ? await inspectSample(source.sampleName, pageIndex)
          : await inspectFile(source.blob as Blob, password || undefined, pageIndex, source.fileName);
      setInspectReport(report);
      const page: InspectPage | undefined = report.pages[pageIndex];
      if (page) {
        commitHistory();
        const built = buildBoxesFromInspectPage(page, pageIndex);
        const removedIds = new Set(regions.filter((r) => r.page === pageIndex).map((r) => r.id));
        setRegions((prev) => [...prev.filter((r) => r.page !== pageIndex), ...built.regions]);
        setColumns((prev) => [...prev.filter((c) => !removedIds.has(c.regionId)), ...built.columns]);
        setSingles((prev) => [...prev.filter((s) => s.page !== pageIndex), ...built.singles]);
        if (built.regions[0]) setActiveRegionId(built.regions[0].id);
        setNotice(`已完成第 ${pageIndex + 1} 页 OCR 识字与列识别（识别出 ${built.columns.length} 列）。`);
      }
    } catch (e) {
      setError((e as Error).message || '本页 OCR 识别失败');
    } finally {
      setBusy(false);
    }
  };

  const handleSpread = async (kwOverride?: string, targetPageIdx?: number) => {
    const kw = (kwOverride ?? keyword).trim();
    if (!kw) {
      setError('请先输入表头关键字（例如「交易日期」「摘要」「余额」）。');
      return;
    }
    if (!source.blob && !source.sampleName) return;
    setBusy(true);
    setError('');
    try {
      const pIdx = targetPageIdx ?? pageIndex;
      const res =
        source.mode === 'sample' && source.sampleName
          ? await spreadKeyword(source.sampleName, kw, pIdx)
          : await spreadFile(source.blob as Blob, kw, password || undefined, pIdx, source.fileName);
      const band = res.bands.find((b) => b.page === pIdx) || res.bands[0];
      if (!band) {
        setNotice(`未在当前页找到「${kw}」关键字列。可改用工具栏「+ 框选列」直接拖框。`);
        return;
      }
      const W = band.width || inspectReport?.pages[band.page]?.width || pageSize.w;
      const H = band.height || inspectReport?.pages[band.page]?.height || pageSize.h;
      const nx = Math.max(0, Math.min(0.98, band.x0 / W));
      const nw = Math.max(0.015, Math.min(1 - nx, (band.x1 - band.x0) / W));

      commitHistory();
      let rid = activeRegionId;
      const pageRegs = regions.filter((r) => r.page === band.page);
      if (!rid || !pageRegs.some((r) => r.id === rid)) {
        if (pageRegs[0]) {
          rid = pageRegs[0].id;
        } else {
          rid = uid('reg');
          setRegions((prev) => [
            ...prev,
            {
              id: rid as string,
              page: band.page,
              slot: band.page === 0 ? 'first' : 'middle',
              area: { x: 0.03, y: 0.16, w: 0.94, h: 0.76 },
              headerY: 0.16,
            },
          ]);
        }
      }
      const newCol: ColumnBox = {
        id: uid('col'),
        regionId: rid,
        field: 'summary',
        x: nx,
        w: nw,
        source: band.source || 'spread',
        confidence: 0.9,
        cells: band.cells || [],
        cellNorms: (band.cells || []).slice(0, 12).map((c) => ({
          x0: Math.max(0, c.x0 / W),
          x1: Math.min(1, c.x1 / W),
          y0: Math.max(0, c.y0 / H),
          y1: Math.min(1, c.y1 / H),
          text: c.text,
        })),
      };
      setColumns((prev) => [...prev, newCol]);
      setSelected({ kind: 'col', id: newCol.id });
      setTool('select');
      setNotice(`已由「${kw}」自动识别出 1 列（${band.cells?.length || 0} 条数据），请在右侧选择它对应的业务字段。`);
    } catch (e) {
      setError((e as Error).message || '点词识别失败');
    } finally {
      setBusy(false);
    }
  };

  const handleSpreadAt = async (nx: number, ny: number) => {
    const ip = inspectReport?.pages[pageIndex];
    if (ip && ip.width > 0 && ip.height > 0) {
      const px = nx * ip.width;
      const py = ny * ip.height;
      // Search inspect cells near clicked coordinates for candidate header/word
      const allBands = [...(ip.bands || []), ...(ip.regions || []).flatMap((r) => r.bands || [])];
      for (const b of allBands) {
        if (px >= b.x0 && px <= b.x1) {
          const hitCell = (b.cells || []).find((c) => Math.abs((c.y0 + c.y1) / 2 - py) < 28) || b.cells?.[0];
          if (hitCell?.text) {
            setKeyword(hitCell.text);
            await handleSpread(hitCell.text, pageIndex);
            return;
          }
        }
      }
    }
    if (keyword.trim()) {
      await handleSpread(keyword, pageIndex);
    } else {
      setNotice('当前位置无已识字锚点词，请在右侧「点词自动扩展」输入框填关键字，或切换「+ 框选列」直接拖框。');
    }
  };

  const ensureActiveRegionOnPage = useCallback((): string => {
    const onPage = regions.filter((r) => r.page === pageIndex);
    if (activeRegionId && onPage.some((r) => r.id === activeRegionId)) {
      return activeRegionId;
    }
    if (onPage[0]) {
      setActiveRegionId(onPage[0].id);
      return onPage[0].id;
    }
    const newId = uid('reg');
    setRegions((prev) => [
      ...prev,
      {
        id: newId,
        page: pageIndex,
        slot: pageIndex === 0 ? 'first' : 'middle',
        area: { x: 0.03, y: 0.16, w: 0.94, h: 0.76 },
        headerY: 0.16,
      },
    ]);
    setActiveRegionId(newId);
    return newId;
  }, [regions, pageIndex, activeRegionId]);

  const handleCreateRegion = (area: { x: number; y: number; w: number; h: number }) => {
    const newId = uid('reg');
    setRegions((prev) => [
      ...prev,
      {
        id: newId,
        page: pageIndex,
        slot: pageIndex === 0 ? 'first' : 'middle',
        area,
        headerY: area.y,
      },
    ]);
    setActiveRegionId(newId);
    setSelected({ kind: 'region', id: newId });
    setTool('select');
  };

  const handleCreateColumn = (box: { x: number; w: number; regionId?: string }) => {
    const rid = box.regionId || ensureActiveRegionOnPage();
    const newId = uid('col');
    setColumns((prev) => [
      ...prev,
      {
        id: newId,
        regionId: rid,
        field: 'summary',
        x: box.x,
        w: box.w,
        source: 'manual',
        confidence: 1,
        cells: [],
      },
    ]);
    setSelected({ kind: 'col', id: newId });
    setTool('select');
  };

  const handleCreateSingle = (rect: { x: number; y: number; w: number; h: number }) => {
    const newId = uid('meta');
    setSingles((prev) => [
      ...prev,
      {
        id: newId,
        field: 'account_no',
        label: '卡号或账号',
        value: '',
        page: pageIndex,
        x: rect.x,
        y: rect.y,
        w: rect.w,
        h: rect.h,
        manual: true,
      },
    ]);
    setSelected({ kind: 'single', id: newId });
    setTool('select');
  };

  const handleDryRun = async () => {
    if (!source.blob) {
      setError('请先选择测试样本或上传待标注的流水文件再试跑。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const { fieldMap, layout } = buildTemplatePayload(regions, columns, singles, customFields, pageSize, pageCount);
      const res = await previewDraftTemplate({
        file: source.blob,
        fileName: source.fileName,
        bankCode: bankCode || 'OTHER',
        fieldMap,
        layout,
        requiredFields,
        password: password || undefined,
      });
      setPreview(res);
    } catch (e) {
      setError((e as Error).message || '试跑解析失败');
    } finally {
      setBusy(false);
    }
  };

  const handleSaveTemplate = async (publish: boolean) => {
    if (!bankCode.trim()) {
      setError('请先在右侧「第二步：填写银行与基础设置」选择或输入银行代码。');
      return;
    }
    if (columns.length === 0) {
      setError('请至少标注 1 个表格列框后再保存模板。');
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const { fieldMap, layout } = buildTemplatePayload(regions, columns, singles, customFields, pageSize, pageCount);
      const res = await saveTemplateFromCanvas({
        bankCode: bankCode.trim().toUpperCase(),
        fieldMap,
        layout,
        requiredFields,
        templateId: editingTemplateId,
        publish,
        file: source.blob,
        fileName: source.fileName,
      });
      setEditingTemplateId(res.id);
      setSavedBanner({ id: res.id, version: res.version, status: res.status });
      listTemplates(false).then(setTemplates).catch(() => {});
      navigate(`/bank/annotate?templateId=${res.id}`, { replace: true });
      setNotice(
        publish
          ? `已保存并启用模板 #${res.id}（${bankLabel(res.bank_code)} v${res.version}）。`
          : `已保存为草稿模板 #${res.id}（${bankLabel(res.bank_code)} v${res.version}）。`,
      );
    } catch (e) {
      setError((e as Error).message || '保存模板失败');
    } finally {
      setBusy(false);
    }
  };

  const handleReparseTask = async () => {
    if (!editingTaskId) return;
    setBusy(true);
    setError('');
    try {
      const { fieldMap, layout } = buildTemplatePayload(regions, columns, singles, customFields, pageSize, pageCount);
      await reparseTaskCanvas(editingTaskId, {
        fieldMap,
        layout,
        bankCode: bankCode.trim().toUpperCase() || undefined,
      });
      setNotice(`已按当前框选重解析任务 #${editingTaskId}。`);
    } catch (e) {
      setError((e as Error).message || '临时重解析任务失败');
    } finally {
      setBusy(false);
    }
  };

  const pageRegions = regions.filter((r) => r.page === pageIndex);
  const currentRegion = pageRegions.find((r) => r.id === activeRegionId) || pageRegions[0];

  const validationIssues: ValidationIssue[] = [];
  if (!bankCode.trim()) {
    validationIssues.push({ code: 'T001', level: 'error', message: '未选择或填写银行代码' });
  }
  if (columns.length === 0) {
    validationIssues.push({ code: 'T002', level: 'error', message: '尚未标注任何交易列框' });
  } else {
    const mappedSet = new Set<string>();
    for (const c of columns) {
      for (const fk of c.fields?.length ? c.fields : [c.field]) {
        mappedSet.add(fk);
        if (fk === 'counterparty_name') mappedSet.add('counterparty');
        if (fk === 'counterparty') mappedSet.add('counterparty_name');
      }
    }
    const missingReq = requiredFields.filter((f) => !mappedSet.has(f));
    if (missingReq.length > 0) {
      validationIssues.push({ code: 'T003', level: 'warn', message: `缺少必需列：${missingReq.join('、')}` });
    }
    for (const r of pageRegions) {
      const rCols = columns.filter((c) => c.regionId === r.id).sort((a, b) => a.x - b.x);
      for (let i = 1; i < rCols.length; i++) {
        const prev = rCols[i - 1];
        const cur = rCols[i];
        if (prev.x + prev.w - cur.x > 0.015) {
          validationIssues.push({
            code: 'T004',
            level: 'warn',
            message: `列「${prev.field}」与「${cur.field}」横向重叠，建议微调宽度`,
            target: { kind: 'col', id: cur.id },
          });
          break;
        }
      }
    }
  }

  const handleSlotChange = (slot: PageSlot) => {
    if (!currentRegion) return;
    commitHistory();
    setRegions((prev) => prev.map((r) => (r.id === currentRegion.id ? { ...r, slot } : r)));
  };

  return (
    <div className={focusWork ? 'ann-page focus' : 'ann-page'}>
      {!focusWork && (
        <header className="ann-top-bar">
          <div>
            <h2>模板与流水画布标注工作台</h2>
            <p className="muted">
              支持自动识列、鼠标拖框增改表格区/列框/单值框、跨页首页/续页/末页版式、自定义字段与实时试跑。
            </p>
          </div>
          <div className="ann-top-actions">
            {editingTaskId && (
              <Button size="sm" variant="ghost" onClick={() => navigate(`/bank/report/${editingTaskId}`)}>
                返回任务 #{editingTaskId} 报告
              </Button>
            )}
            {/* 保存按钮放在顶栏：右栏是可滚动的，保存区常常被推到屏幕外，用户找不到就无法落库 */}
            <Button size="sm" variant="secondary" onClick={() => handleSaveTemplate(false)} disabled={busy || columns.length === 0}>
              仅存草稿
            </Button>
            {isAdmin && (
              <Button size="sm" onClick={() => handleSaveTemplate(true)} disabled={busy || columns.length === 0}>
                保存并启用
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => navigate('/bank/templates')}>
              返回模板列表
            </Button>
          </div>
        </header>
      )}

      {error && <div className="alert err">{error}</div>}
      {notice && <div className="alert ok">{notice}</div>}
      {savedBanner && (
        <div className="alert ok">
          模板 #{savedBanner.id}（v{savedBanner.version}，状态：{savedBanner.status === 'enabled' ? '已启用' : '草稿'}）已落库。
          <Link to={`/bank/templates/${savedBanner.id}`} style={{ marginLeft: 10 }}>
            查看模板详情与对比 ›
          </Link>
          <Link to={`/bank/templates/${savedBanner.id}/layout`} style={{ marginLeft: 10 }}>
            查看只读示意图 ›
          </Link>
        </div>
      )}

      <AnnotateToolbar
        tool={tool}
        onToolChange={setTool}
        pageIndex={pageIndex}
        pageCount={pageCount}
        onPageChange={(idx) => {
          setPageIndex(Math.max(0, Math.min(pageCount - 1, idx)));
          setSelected(null);
        }}
        currentSlot={currentRegion?.slot}
        onSlotChange={handleSlotChange}
        zoom={zoom}
        onZoomChange={setZoom}
        showBoxes={showBoxes}
        onToggleBoxes={() => setShowBoxes((v) => !v)}
        focusWork={focusWork}
        onToggleFocus={() => setFocusWork((v) => !v)}
        canUndo={past.length > 0}
        canRedo={future.length > 0}
        onUndo={handleUndo}
        onRedo={handleRedo}
        ocrUsed={inspectReport?.ocr_used}
        onReOcrPage={handleReOcrPage}
        busy={busy}
      />

      <div className="ann-workspace">
        <div className="ann-stage-col">
          <CanvasStage
            fileBytes={source.bytes}
            mimeHint={source.mimeHint}
            pageIndex={pageIndex}
            zoom={zoom}
            password={password || undefined}
            tool={tool}
            showBoxes={showBoxes}
            regions={regions}
            columns={columns}
            singles={singles}
            customFields={customFields}
            activeRegionId={currentRegion?.id ?? null}
            selected={selected}
            onSelect={setSelected}
            onSelectRegion={setActiveRegionId}
            onUpdateRegion={(id, patch) => setRegions((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)))}
            onCreateRegion={handleCreateRegion}
            onUpdateColumn={(id, patch) => setColumns((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)))}
            onCreateColumn={handleCreateColumn}
            onUpdateSingle={(id, patch) => setSingles((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)))}
            onCreateSingle={handleCreateSingle}
            onCommitHistory={commitHistory}
            onPageInfo={(info: PageRenderSize) => {
              setPageCount(info.pageCount || 1);
              setPageSize({ w: Math.round(info.baseWidth), h: Math.round(info.baseHeight) });
            }}
            onPasswordRequired={() => setNeedPassword(true)}
            onError={setError}
            onSpreadAt={handleSpreadAt}
          />
          <PreviewDrawer
            preview={preview}
            onClose={() => setPreview(null)}
            onSwapAmountBalance={handleSwapAmountBalance}
          />
        </div>

        <StepSidebar
          samples={samples}
          tasks={tasks}
          templates={templates}
          sourceMode={source.mode}
          sourceLabel={source.label}
          onSelectSample={(name) => loadSampleSource(name, keepLayoutOnUpload && (columns.length > 0 || singles.length > 0))}
          onSelectFile={(file) => void handleUploadFileSource(file)}
          onSelectTask={handleSelectTaskSource}
          onSelectTemplate={(tid) => void loadTemplateById(tid)}
          keepLayoutOnUpload={keepLayoutOnUpload}
          onToggleKeepLayout={setKeepLayoutOnUpload}
          onAnalyzeFields={(s, h) => void handleAnalyzeFieldsInCanvas(s, h)}
          needPassword={needPassword}
          password={password}
          onPasswordChange={setPassword}
          onRetryWithPassword={() => {
            const pZip = pendingZipRef.current;
            if (pZip) {
              if (pZip.attempts >= 3) {
                setError('压缩包口令连续输错 3 次，已停止解压；请核对客户口令后重选文件。');
                pendingZipRef.current = null;
                return;
              }
              extractStatement(pZip.file, password)
                .then((out) => {
                  if (out.status === 'wrong-password' || out.status === 'need-password') {
                    pZip.attempts += 1;
                    setError(`口令不正确（已尝试 ${pZip.attempts}/3 次），请重试。`);
                    return;
                  }
                  pendingZipRef.current = null;
                  setNeedPassword(false);
                  const preserve = keepLayoutOnUpload && (columns.length > 0 || singles.length > 0);
                  void loadBlobSource(out.blob, out.name, 'file', `${pZip.file.name} › ${out.name}`, undefined, preserve, 0);
                })
                .catch((e) => setError((e as Error).message || '解压失败'));
              return;
            }
            if (source.blob) {
              const preserve = keepLayoutOnUpload && (columns.length > 0 || singles.length > 0);
              void loadBlobSource(source.blob, source.fileName, source.mode === 'sample' ? 'file' : source.mode, source.label, password, preserve, pageIndex);
            }
          }}
          bankCode={bankCode}
          onBankCodeChange={setBankCode}
          pageRegions={pageRegions}
          activeRegionId={currentRegion?.id ?? null}
          onSelectRegion={setActiveRegionId}
          onDeleteRegion={(id) => {
            commitHistory();
            setRegions((prev) => prev.filter((r) => r.id !== id));
            setColumns((prev) => prev.filter((c) => c.regionId !== id));
            if (selected?.kind === 'region' && selected.id === id) setSelected(null);
          }}
          onStartDrawArea={() => setTool('draw_area')}
          columns={columns}
          selected={selected}
          onSelect={setSelected}
          onUpdateColumn={(id, patch) => {
            commitHistory();
            setColumns((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)));
          }}
          onDeleteColumn={(id) => {
            commitHistory();
            setColumns((prev) => prev.filter((c) => c.id !== id));
            if (selected?.kind === 'col' && selected.id === id) setSelected(null);
          }}
          onStartDrawCol={() => setTool('draw_col')}
          singles={singles}
          onUpdateSingle={(id, patch) => {
            commitHistory();
            setSingles((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
          }}
          onDeleteSingle={(id) => {
            commitHistory();
            setSingles((prev) => prev.filter((s) => s.id !== id));
            if (selected?.kind === 'single' && selected.id === id) setSelected(null);
          }}
          onStartDrawSingle={() => setTool('draw_single')}
          customFields={customFields}
          onAddCustomField={(opt) => setCustomFields((prev) => (prev.some((f) => f.key === opt.key) ? prev : [...prev, opt]))}
          requiredFields={requiredFields}
          onToggleRequired={(fk) =>
            setRequiredFields((prev) => (prev.includes(fk) ? prev.filter((k) => k !== fk) : [...prev, fk]))
          }
          keyword={keyword}
          onKeywordChange={setKeyword}
          onSpread={() => handleSpread()}
          onDryRun={handleDryRun}
          onSaveTemplate={handleSaveTemplate}
          onReparseTask={editingTaskId ? handleReparseTask : undefined}
          validationIssues={validationIssues}
          editingTemplateId={editingTemplateId}
          editingTaskId={editingTaskId}
          isAdmin={isAdmin}
          busy={busy}
        />
      </div>
    </div>
  );
}

export default AnnotatePage;
