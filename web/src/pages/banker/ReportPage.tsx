import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  createApproval,
  exportPrintableReport,
  getBankTask,
  getMetricDefinitions,
  getReport,
  getTaskExportWithMeta,
  getTaskFile,
  getTransactions,
  getVerificationDefinitions,
  listTemplates,
  reanalyzeTask,
  verifyTask,
  whitelistTask,
  type MetricDef,
  type ReportPayload,
  type TaskBankDetail,
  type TemplateRow,
  type TxnRow,
} from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { getUser } from '../../auth/store';
import { CheckTable } from '../../components/CheckTable';
import { MetricExplain } from '../../components/MetricExplain';
import { PdfPageCanvas, type PageRenderSize } from '../../components/PdfPageCanvas';
import { AmountHistogram, Bar, DomainRadar, InsightSection, MonthlyFlow } from '../../components/ReportCharts';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';

type Tab = 'summary' | 'verify' | 'metrics' | 'evidence' | 'txns';

const TABS: { key: Tab; label: string }[] = [
  { key: 'summary', label: '结论与评分' },
  { key: 'verify', label: '四层核验与自检' },
  { key: 'metrics', label: '40 项指标' },
  { key: 'evidence', label: '证据与原件定位' },
  { key: 'txns', label: '交易流水明细' },
];

const TASK_STATUS_LABEL: Record<string, string> = {
  PENDING: '待排队',
  QUEUED: '排队中',
  PARSING: '解析中',
  VERIFYING: '核验中',
  REPORTING: '出报告中',
  DONE: '已完成',
  NEED_SUPPLEMENT: '需补件',
  FAILED: '失败',
};

function statusLabel(code: string): string {
  return TASK_STATUS_LABEL[code] || code;
}

const DOMAIN: Record<string, string> = {
  A: '收入能力',
  B: '负债与还款',
  C: '资金往来',
  D: '异常与风险',
  E: '语义与场景',
};

type LayerCheck = {
  code?: string;
  name?: string;
  method?: string;
  status?: string;
  detail?: string;
};

type LayerWithChecks = {
  layer: string;
  status: string;
  detail: string;
  checks?: LayerCheck[];
};

type SelfCheckData = {
  status?: string;
  summary?: string;
  items?: { code: string; name: string; status: string; detail?: string; ratio?: number | null }[];
};

type VerificationData = {
  status?: string;
  changed?: boolean;
  checked_at?: string;
  verified_at?: string;
  txn_count_fast?: number;
  txn_count_slow?: number;
  diff_count?: number;
  diffs?: Record<string, unknown>[];
  reason?: string;
  coverage?: number;
  summary?: string;
  notes?: string[];
};

function verifyStatusMeta(status?: string) {
  switch (status) {
    case 'passed':
    case 'verified':
      return { cls: 'pill ok', label: '已复核' };
    case 'discrepancy':
      return { cls: 'pill err', label: '发现差异' };
    case 'failed':
      return { cls: 'pill warn', label: '复核未完成' };
    case 'pending':
      return { cls: 'pill warn', label: '待复核' };
    default:
      return { cls: 'pill', label: status || '—' };
  }
}

function isNormalizedCoord(x?: number, y?: number): boolean {
  return x !== undefined && y !== undefined && x >= 0 && x <= 1 && y >= 0 && y <= 1;
}

type CustomStatItem = {
  field: string;
  label?: string;
  count?: number;
  numeric?: number;
  valued_count?: number;
  total_count?: number;
  sum?: string | null;
  avg?: string | null;
  samples?: string[];
};

function layerName(layer: string) {
  return { file: '载体层', content: '内容层', ledger: '账务层', external: '外部层' }[layer] ?? layer;
}

function checkStatusBadge(status?: string) {
  switch (status) {
    case 'pass':
      return { cls: 'pill ok', label: '通过' };
    case 'fail':
    case 'inconsistent':
      return { cls: 'pill err', label: '不通过' };
    case 'warn':
    case 'limited':
      return { cls: 'pill warn', label: '受限/告警' };
    default:
      return { cls: 'pill', label: status || '跳过' };
  }
}

const APPROVAL_LABEL: Record<string, { label: string; cls: string }> = {
  approve: { label: '建议通过', cls: 'pill ok' },
  reject: { label: '建议拒绝', cls: 'pill err' },
  supplement: { label: '补充资料', cls: 'pill warn' },
  hold: { label: '暂缓/转人工复议', cls: 'pill warn' },
};

function buildNarrative(report: ReportPayload): string {
  const trustScore = report.trust?.score;
  const overall = report.scores?.overall;
  const limitations = report.limitations?.length ?? 0;
  const parts = [`综合结论为「${report.verdict}」（${report.verdict_reason}）。`];
  if (typeof trustScore === 'number') {
    parts.push(`四层真实性得分 ${trustScore}（${report.trust?.label || '—'}）。`);
  }
  if (typeof overall === 'number') {
    parts.push(`五维综合信用评分 ${overall}（${report.scores?.grade_label || report.scores?.grade || '—'}）。`);
  }
  if (report.conclusions?.length) {
    parts.push(`命中风险/提示结论 ${report.conclusions.length} 条。`);
  }
  if (limitations > 0) {
    parts.push(`存在 ${limitations} 项核验受限说明，审贷前建议核阅。`);
  }
  return parts.join('');
}

export default function ReportPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const taskId = Number(id);
  const isAdmin = Boolean(getUser()?.is_admin);

  const [report, setReport] = useState<ReportPayload | null>(null);
  const [taskMeta, setTaskMeta] = useState<TaskBankDetail | null>(null);
  const [metricDefs, setMetricDefs] = useState<Record<string, MetricDef>>({});
  const [checkMethods, setCheckMethods] = useState<Record<string, string>>({});
  const [templates, setTemplates] = useState<TemplateRow[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [tab, setTab] = useState<Tab>('summary');
  const [viewMode, setViewMode] = useState<'brief' | 'detail'>('detail');
  const [txns, setTxns] = useState<TxnRow[] | null>(null);
  const [txnPage, setTxnPage] = useState(0);
  const [keyword, setKeyword] = useState('');
  const [highlightRow, setHighlightRow] = useState<number | null>(null);
  const highlightRef = useRef<HTMLTableRowElement | null>(null);
  const [openMetric, setOpenMetric] = useState<string | null>(null);

  // 证据原件预览抽屉
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [fileBytes, setFileBytes] = useState<ArrayBuffer | null>(null);
  const [fileMime, setFileMime] = useState('application/pdf');
  const [fileLoading, setFileLoading] = useState(false);
  const [docPageIdx, setDocPageIdx] = useState(0);
  const [docPageCount, setDocPageCount] = useState(1);
  const [docBaseSize, setDocBaseSize] = useState<PageRenderSize | null>(null);
  const [marker, setMarker] = useState<{ page: number; x?: number; y?: number; label?: string } | null>(null);
  const [docPassword, setDocPassword] = useState('');
  const [docPasswordInput, setDocPasswordInput] = useState('');
  const [needDocPassword, setNeedDocPassword] = useState(false);
  const [docPasswordWrong, setDocPasswordWrong] = useState(false);
  const [docRenderError, setDocRenderError] = useState('');

  // 加白、复核与审批意见状态
  const [whitelistOpen, setWhitelistOpen] = useState(false);
  const [whitelistReason, setWhitelistReason] = useState('');
  const [approvalDecision, setApprovalDecision] = useState<'approve' | 'reject' | 'supplement' | 'hold'>('approve');
  const [approvalComment, setApprovalComment] = useState('');
  const [actionBusy, setActionBusy] = useState(false);

  const PAGE = 100;

  const loadReport = useCallback(() => {
    // 报告 404 时也要把任务本身读出来：否则页面只能显示「报告不存在」，
    // 用户不知道是任务失败、还在排队，还是报告真的被删了。
    Promise.all([
      getReport(taskId)
        .then((rep) => ({ ok: true as const, rep }))
        .catch((err) => ({ ok: false as const, err })),
      getBankTask(taskId).catch(() => null),
      getMetricDefinitions().catch(() => ({ items: [] as MetricDef[] })),
      getVerificationDefinitions().catch(() => ({ items: [] as { code: string; method: string }[] })),
      listTemplates().catch(() => [] as TemplateRow[]),
    ])
      .then(([repRes, taskData, defsData, verData, tplList]) => {
        if (repRes.ok) {
          setReport(repRes.rep);
          setError('');
        } else {
          setReport(null);
          setError(getErrorMessage(repRes.err, 'banker'));
        }
        if (taskData) setTaskMeta(taskData);
        const dMap: Record<string, MetricDef> = {};
        for (const d of defsData.items || []) dMap[d.code] = d;
        setMetricDefs(dMap);
        const mMap: Record<string, string> = {};
        for (const v of verData.items || []) mMap[v.code] = v.method;
        setCheckMethods(mMap);
        setTemplates(tplList.filter((t) => t.status === 'enabled'));
      })
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  }, [taskId]);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  useEffect(() => {
    if (txns) return;
    let alive = true;
    getTransactions(taskId)
      .then((rows) => alive && setTxns(rows))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [taskId, txns]);

  const openOriginalAt = async (pageNo = 1, x?: number, y?: number, label?: string) => {
    setDrawerOpen(true);
    setDocPageIdx(Math.max(0, pageNo - 1));
    setMarker({ page: Math.max(0, pageNo - 1), x, y, label });
    if (fileBytes) return;
    setFileLoading(true);
    try {
      const blob = await getTaskFile(taskId);
      setFileMime(blob.type || 'application/pdf');
      setFileBytes(await blob.arrayBuffer());
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setFileLoading(false);
    }
  };

  const handleExport = async (fmt: 'json' | 'csv' | 'html') => {
    try {
      const { blob, filename } =
        fmt === 'html' ? await exportPrintableReport(taskId) : await getTaskExportWithMeta(taskId, fmt);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename || `task-${taskId}.${fmt}`;
      a.click();
      URL.revokeObjectURL(url);
      if (fmt === 'html') setNotice('已导出带水印的核验报告，请查收下载文件。');
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    }
  };

  const handleReanalyzeWithTemplate = async () => {
    const tid = Number(selectedTemplateId);
    if (!tid) return;
    setActionBusy(true);
    setError('');
    setNotice('');
    try {
      await reanalyzeTask(taskId, { templateId: tid });
      setNotice(`已指定模板 #${tid} 重解析完成，正在刷新报告…`);
      setTxns(null);
      loadReport();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setActionBusy(false);
    }
  };

  const handleApprovalSubmit = async () => {
    if (!approvalComment.trim()) return;
    setActionBusy(true);
    setError('');
    setNotice('');
    try {
      await createApproval(taskId, { decision: approvalDecision, comment: approvalComment.trim() });
      setApprovalComment('');
      setNotice('审批意见已归档并绑定当前报告版本。');
      loadReport();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setActionBusy(false);
    }
  };

  const handleManualVerify = async () => {
    setActionBusy(true);
    setError('');
    setNotice('');
    try {
      await verifyTask(taskId);
      setNotice('已完成慢通道复核并更新报告。');
      loadReport();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setActionBusy(false);
    }
  };

  const handleWhitelist = async () => {
    if (!whitelistReason.trim()) return;
    setActionBusy(true);
    setError('');
    try {
      await whitelistTask(taskId, whitelistReason.trim());
      setWhitelistOpen(false);
      setWhitelistReason('');
      setNotice('已将该任务录入人工核实白名单并留存审计。');
      loadReport();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setActionBusy(false);
    }
  };

  const metrics = report?.metrics ?? [];
  const grouped = useMemo(() => {
    const out: Record<string, typeof metrics> = {};
    for (const metric of metrics) {
      const domain = DOMAIN[metric.code.slice(0, 1)] ?? '其它';
      (out[domain] ??= []).push(metric);
    }
    return out;
  }, [metrics]);

  useEffect(() => {
    if (tab === 'txns' && highlightRef.current) {
      highlightRef.current.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [tab, highlightRow, txnPage, txns]);

  const filteredTxns = useMemo(() => {
    const rows = txns ?? [];
    const key = keyword.trim();
    if (!key) return rows;
    return rows.filter((row) =>
      [row.summary, row.counterparty_name, row.amount, row.balance, row.txn_date]
        .filter(Boolean)
        .some((field) => String(field).includes(key)),
    );
  }, [txns, keyword]);

  const metricThresholdHints = useMemo(() => {
    const map: Record<string, string> = {};
    for (const c of report?.conclusions || []) {
      if (c.threshold !== undefined && c.threshold !== null) {
        map[c.code] = `触发阈值 ${c.threshold}（实测 ${c.value ?? '—'}）`;
      }
    }
    return map;
  }, [report?.conclusions]);

  if (error && !report) {
    const st = taskMeta?.status || '';
    const why: Record<string, string> = {
      PENDING: '任务还在排队，报告要等解析跑完才会生成。',
      QUEUED: '任务在队列里等进程，报告还没生成。',
      PARSING: '正在解析原件，通常几十秒内出报告。',
      NEED_SUPPLEMENT: '分析结论是「需补件」：请补齐材料后会自动重跑，报告随之更新。',
      FAILED: '任务失败了，所以没有报告；可以直接重试或看队列里的失败原因。',
    };
    return (
      <div className="panel wide">
        <Notice>{error}</Notice>
        <div className="report-missing">
          <p>
            任务 #{taskId}
            {st ? <> · 当前状态 <b>{statusLabel(st)}</b></> : null}
            {taskMeta?.failure_code ? <> · 失败码 <b>{taskMeta.failure_code}</b></> : null}
          </p>
          {st && why[st] ? <p className="muted">{why[st]}</p> : null}
          <div className="empty-actions">
            {st === 'FAILED' ? (
              <Link className="btn" to="/bank/queue">去任务队列重试</Link>
            ) : null}
            <Link className="btn btn-ghost" to="/bank/tasks">回到任务列表</Link>
            <button className="btn btn-ghost" onClick={loadReport}>重新加载</button>
          </div>
        </div>
      </div>
    );
  }

  // 两个提前返回都在所有 hook 之后：hook 数随渲染变化会让 React 报
  // 「change in the order of Hooks」并整页白屏（广发样例就是这么白掉的）
  if (!report) return <p className="muted">加载中…</p>;

  const trustScore = report.trust?.score;
  const overallScore = report.scores?.overall;
  const valued = metrics.filter((metric) => metric.value !== null).length;
  const verification = (report.verification || {}) as VerificationData;
  const selfCheck = report.self_check as SelfCheckData | SelfCheckData['items'] | null | undefined;
  const selfCheckItems = Array.isArray(selfCheck) ? selfCheck : (selfCheck?.items ?? []);
  const customStats = Array.isArray(report.custom_field_stats)
    ? (report.custom_field_stats as CustomStatItem[])
    : [];
  const layers = (report.layers ?? []) as LayerWithChecks[];
  const hasTemplateMismatch =
    (report.limitations ?? []).some((l) => /模板缺列|解析不完整|模板|临时标注/.test(l)) ||
    Boolean(taskMeta?.check_result?.template_mismatch);
  const vetoChecks = layers.flatMap((l) =>
    (l.checks ?? []).filter((c) => ['C1', 'C2', 'C3'].includes(String(c.code || '')) && (c.status === 'fail' || c.status === 'inconsistent')),
  );
  const inTrash = Boolean((report as unknown as { in_trash?: boolean }).in_trash);
  const preread = taskMeta?.check_result?.preread as Record<string, unknown> | undefined;
  const matchedTpl =
    taskMeta?.check_result?.matched_template || taskMeta?.check_result?.template_match || null;
  const whitelistInfo = taskMeta?.check_result?.whitelist || null;
  const headerMeta = (report.header_meta || taskMeta?.check_result?.header_meta || {}) as Record<string, unknown>;
  const extraHeaderFields = (headerMeta.extra_fields && typeof headerMeta.extra_fields === 'object'
    ? headerMeta.extra_fields
    : {}) as Record<string, unknown>;

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <div className="report-title-row">
            <h1>{report.verdict}</h1>
            <span className={verifyStatusMeta(verification.status).cls}>
              复核：{verifyStatusMeta(verification.status).label}
              {verification.status === 'discrepancy' && typeof verification.diff_count === 'number'
                ? `（${verification.diff_count} 处）`
                : ''}
            </span>
          </div>
          <p className="sub">{report.verdict_reason}</p>
        </div>
        <div className="filters no-print">
          <Button size="sm" onClick={() => navigate('/bank/annotate?taskId=' + taskId)}>
            画布调框重解析
          </Button>
          <Button size="sm" variant="ghost" disabled={actionBusy} onClick={() => void handleManualVerify()}>
            手动复核
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setWhitelistOpen((v) => !v)}>
            误判加白
          </Button>
          <Button size="sm" variant="ghost" onClick={() => void handleExport('json')}>
            导出结论 JSON
          </Button>
          {isAdmin && (
            <Button size="sm" variant="ghost" onClick={() => void handleExport('csv')}>
              导出明细 CSV
            </Button>
          )}
          <Button size="sm" variant="ghost" disabled={actionBusy} onClick={() => void handleExport('html')}>
            导出带水印报告
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              const next = viewMode === 'brief' ? 'detail' : 'brief';
              setViewMode(next);
              if (next === 'brief') setTab('summary');
            }}
          >
            {viewMode === 'brief' ? '切换明细版' : '切换结论版'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setViewMode('brief');
              setTab('summary');
              window.setTimeout(() => window.print(), 80);
            }}
          >
            打印 / 存 PDF
          </Button>
          <Link className="btn btn-ghost" to="/bank/tasks">回到列表</Link>
        </div>
      </header>

      {error && <Notice>{error}</Notice>}
      {notice && <Notice tone="ok">{notice}</Notice>}

      {inTrash && (
        <div className="alert warn no-print">
          当前任务位于回收站中（仅供复核查阅）；如需恢复请前往任务回收站操作。
        </div>
      )}
      {vetoChecks.length > 0 && (
        <div className="alert err" style={{ borderLeft: '4px solid #c0392b', background: '#fdf2f2', padding: '10px 14px', marginBottom: 12 }}>
          <strong>一票否决警示：</strong>关键核验项（{vetoChecks.map((c) => c.code).join('、')}）未通过，
          请重点核查余额链/页合计/笔数一致性后再作授信决策。
        </div>
      )}
      {whitelistInfo && (
        <div className="alert ok" style={{ borderLeft: '4px solid #16a34a', background: '#f0fdf4', padding: '10px 14px', marginBottom: 12 }}>
          <strong>人工核实已加白：</strong>
          {whitelistInfo.reason || '已确认真实有效'}
          {whitelistInfo.at ? <span className="muted small" style={{ marginLeft: 8 }}>（{whitelistInfo.at}）</span> : null}
        </div>
      )}
      {hasTemplateMismatch && (
        <div className="alert warn no-print">
          <div className="row-between">
            <span>
              检测到该任务存在「解析不完整 / 模板缺列 / 版式未命中」提示，可直接指定已有模板重解析或前往画布调框：
            </span>
            <div className="filters">
              <select
                value={selectedTemplateId}
                onChange={(e) => setSelectedTemplateId(e.target.value)}
                aria-label="指定模板重解析"
              >
                <option value="">选择启用模板…</option>
                {templates.map((t) => (
                  <option key={t.id} value={String(t.id)}>
                    {t.bank_code} v{t.version} (#{t.id})
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                disabled={actionBusy || !selectedTemplateId}
                onClick={() => void handleReanalyzeWithTemplate()}
              >
                用所选模板重解析
              </Button>
              <button
                type="button"
                className="link-btn"
                onClick={() => navigate('/bank/annotate?taskId=' + taskId)}
              >
                打开标注工作台 ›
              </button>
            </div>
          </div>
        </div>
      )}

      {whitelistOpen && (
        <div className="import-box no-print">
          <strong>人工复核加白说明（写入不可删审计日志）</strong>
          <div className="try-row" style={{ marginTop: 8 }}>
            <input
              type="text"
              style={{ flex: 1 }}
              placeholder="填写核实依据，如：已电话回访开户行并核验柜面回单一致"
              value={whitelistReason}
              onChange={(e) => setWhitelistReason(e.target.value)}
            />
            <Button size="sm" disabled={actionBusy || !whitelistReason.trim()} onClick={() => void handleWhitelist()}>
              确认加白
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setWhitelistOpen(false)}>取消</Button>
          </div>
        </div>
      )}

      <div className="score-row">
        <div className="score">
          <span className="score-value">{trustScore ?? '—'}</span>
          <span className="muted small">真实性得分{report.trust?.label ? ` · ${report.trust.label}` : ''}</span>
        </div>
        <div className="score">
          <span className="score-value">{overallScore ?? '—'}</span>
          <span className="muted small">综合评分{report.scores?.grade_label ? ` · ${report.scores.grade_label}` : ''}</span>
        </div>
        <div className="score"><span className="score-value">{valued}/{metrics.length}</span><span className="muted small">指标有值</span></div>
        <div className="score"><span className="score-value">{report.materials?.length ?? 0}</span><span className="muted small">提交材料</span></div>
      </div>

      {viewMode === 'detail' && (
      <div className="tabs small-tabs report-tabs no-print">
        {TABS.map((item) => (
          <button key={item.key} className={tab === item.key ? 'active' : ''} onClick={() => setTab(item.key)}>
            {item.label}
          </button>
        ))}
      </div>
      )}

      {tab === 'summary' ? (
        <>
          {(preread || matchedTpl || Object.keys(headerMeta).length > 0 || taskMeta?.consent_version) && (
            <div className="preread-card">
              <div className="row-between">
                <h3>原件识别、模板归因与表头摘要</h3>
                <span className="muted small">
                  报告版本 v{report.version ?? 1}
                  {taskMeta?.consent_version ? ` · 借款人授权 ${taskMeta.consent_version}` : ''}
                </span>
              </div>
              <div className="me-grid" style={{ marginTop: 6 }}>
                <div>
                  <span className="me-k">模板匹配</span>
                  <span className="me-v">
                    {matchedTpl
                      ? `${(matchedTpl as { bank_code?: string }).bank_code || taskMeta?.carrier || '—'} #${(matchedTpl as { template_id?: number; id?: number }).template_id ?? (matchedTpl as { id?: number }).id ?? '—'}（方式：${(matchedTpl as { by?: string }).by || '自动'}）`
                      : '默认规则 / 未绑定特定模板'}
                  </span>
                </div>
                {preread ? (
                  <div>
                    <span className="me-k">预读诊断</span>
                    <span className="me-v">
                      {String(preread.pages ?? '—')} 页 ·
                      {preread.has_text === false ? ' 扫描/图片件' : ' 文本层清晰'}
                      {preread.bank_guess ? ` · 银行猜测 ${String(preread.bank_guess)}` : ''}
                    </span>
                  </div>
                ) : null}
                {headerMeta.bank_branch ? (
                  <div>
                    <span className="me-k">开户网点</span>
                    <span className="me-v">{String(headerMeta.bank_branch)}</span>
                  </div>
                ) : null}
                {headerMeta.currency ? (
                  <div>
                    <span className="me-k">交易币种</span>
                    <span className="me-v">{String(headerMeta.currency)}</span>
                  </div>
                ) : null}
                {headerMeta.account_no ? (
                  <div>
                    <span className="me-k">账号</span>
                    <span className="me-v mono">{String(headerMeta.account_no)}</span>
                  </div>
                ) : null}
                {Object.entries(extraHeaderFields).map(([k, v]) => (
                  <div key={k}>
                    <span className="me-k">{k}</span>
                    <span className="me-v">{String(v ?? '—')}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {viewMode === 'brief' && (
            <div className="summary-panel">
              <h3>结论摘要视图（可直接打印交付审贷会）</h3>
              <p>{buildNarrative(report)}</p>
            </div>
          )}

          <section>
            <h2>四层得分仪表</h2>
            <div className="gauge-row">
              <div className="gauge-card">
                <h3>综合评分</h3>
                <span className="score-value">{report.scores?.overall ?? report.trust?.score ?? '—'}</span>
                <span className="muted small">等级 {report.scores?.grade_label ?? report.trust?.label ?? '—'}</span>
                {report.scores?.method ? <span className="muted small">{report.scores.method}</span> : null}
              </div>
              {report.trust?.layers?.map((layer) => (
                <div key={layer.layer} className="gauge-card">
                  <h3>
                    {layer.label} <span className="muted small">{layer.status}</span>
                  </h3>
                  <span className="score-value small-value">{layer.score}</span>
                  <Bar
                    value={layer.score}
                    tone={layer.status === 'unavailable' ? 'muted' : layer.score >= 80 ? 'brand' : layer.score >= 60 ? 'warn' : 'bad'}
                  />
                  <span className="muted small">权重 {Math.round((layer.weight ?? 0) * 100)}%</span>
                </div>
              ))}
            </div>
          </section>

          {report.scores?.domains?.length ? (
            <section>
              <h2>业务域评估与五维雷达图</h2>
              <div className="domain-split">
                <div className="domain-radar-wrap">
                  <DomainRadar domains={report.scores.domains} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <table className="grid compact">
                    <thead><tr><th>业务域</th><th>得分</th><th>权重</th><th>指标覆盖</th><th>命中线索</th></tr></thead>
                    <tbody>
                      {report.scores.domains.map((domain) => (
                        <tr key={domain.key} className="domain-row">
                          <td>
                            {domain.name}
                            <div className="muted small">{domain.desc}</div>
                          </td>
                          <td>
                            <span className="bar-inline">
                              <Bar value={domain.score} tone={domain.score >= 80 ? 'brand' : domain.score >= 60 ? 'warn' : 'bad'} />
                              <span>{domain.score}</span>
                            </span>
                          </td>
                          <td className="small muted">{Math.round(domain.weight * 100)}%</td>
                          <td className="small muted">{domain.metric_valued}/{domain.metric_total}{domain.missing ? ' · 缺 ' + domain.missing : ''}</td>
                          <td className="small muted">
                            {domain.hits?.length ? '命中 ' + domain.hits.join('、') : domain.detail || '无扣分'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          ) : null}

          {report.trend?.length ? (
            <section>
              <h2>月度收支趋势</h2>
              <MonthlyFlow series={report.trend} />
              <p className="muted small">柱状为当月总流入/总流出，虚线为当月净流入；持续入不敷出需重点核查资金用途。</p>
            </section>
          ) : null}

          {txns && txns.length > 0 && viewMode === 'detail' ? <InsightSection txns={txns} /> : null}

          {customStats.length > 0 && (
            <section>
              <h2>模板自定义扩展字段汇总</h2>
              <table className="grid compact">
                <thead><tr><th>字段</th><th>有值笔数</th><th>数值合计</th><th>均值</th><th>样例</th></tr></thead>
                <tbody>
                  {customStats.map((item) => (
                    <tr key={item.field}>
                      <td>{item.label || item.field} <span className="small muted">({item.field})</span></td>
                      <td>{item.count ?? item.valued_count ?? 0}{item.total_count ? `/${item.total_count}` : ''}</td>
                      <td className="mono">{item.sum ?? '—'}</td>
                      <td className="mono">{item.avg ?? '—'}</td>
                      <td className="small muted">{(item.samples || []).slice(0, 3).join(' / ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {report.conclusions?.length ? (
            <section>
              <h2>风险与审查结论依据</h2>
              <ul className="plain">
                {report.conclusions.map((item, index) => (
                  <li key={index}>
                    <span className={'pill ' + (item.level === 'high' ? 'err' : item.level === 'medium' ? 'warn' : '')}>
                      {item.code}
                    </span>{' '}
                    {item.message}
                    {item.value !== undefined && item.value !== null ? (
                      <span className="muted small" style={{ marginLeft: 8 }}>
                        [实测 {String(item.value)}
                        {item.threshold !== undefined && item.threshold !== null ? ` / 阈值 ${String(item.threshold)}` : ''}]
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="approval-box no-print" style={{ marginTop: 14 }}>
            <div className="row-between">
              <h3>审贷批复与审批意见留痕（绑定报告 v{report.version ?? 1}）</h3>
            </div>
            <div className="try-row" style={{ marginBottom: 10 }}>
              <select
                value={approvalDecision}
                onChange={(e) => setApprovalDecision(e.target.value as 'approve' | 'reject' | 'supplement' | 'hold')}
                aria-label="审批结论"
              >
                <option value="approve">建议通过</option>
                <option value="supplement">补充资料</option>
                <option value="hold">暂缓/转人工复议</option>
                <option value="reject">建议拒绝</option>
              </select>
              <input
                type="text"
                style={{ flex: 1 }}
                placeholder="填写审贷意见、风险缓释条件或退回原因…"
                value={approvalComment}
                onChange={(e) => setApprovalComment(e.target.value)}
              />
              <Button
                size="sm"
                disabled={actionBusy || !approvalComment.trim()}
                onClick={() => void handleApprovalSubmit()}
              >
                提交审批意见
              </Button>
            </div>
            {report.approvals && report.approvals.length > 0 ? (
              <table className="grid compact">
                <thead>
                  <tr><th>时间</th><th>审批人</th><th>结论</th><th>报告版本</th><th>意见内容</th></tr>
                </thead>
                <tbody>
                  {report.approvals.map((a) => {
                    const meta = APPROVAL_LABEL[a.decision] ?? { label: a.decision, cls: 'pill' };
                    return (
                      <tr key={a.id}>
                        <td className="small muted">{a.created_at || '—'}</td>
                        <td className="small">{a.actor_name}</td>
                        <td><span className={meta.cls}>{meta.label}</span></td>
                        <td className="small muted">v{a.report_version}</td>
                        <td className="small">{a.comment}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p className="muted small">当前报告版本暂无人工审批批复意见。</p>
            )}
          </section>

          {report.limitations?.length ? (
            <section>
              <h2>核验受限说明（{report.limitations.length}）</h2>
              <ul className="plain">
                {report.limitations.map((item, index) => <li key={index}>{item}</li>)}
              </ul>
            </section>
          ) : null}
        </>
      ) : null}

      {tab === 'verify' ? (
        <section>
          <h2>四层真实性核验明细</h2>
          {layers.map((layer) => (
            <div key={layer.layer} className="verify-block">
              <h3>
                {layerName(layer.layer)} <span className="pill">{layer.status}</span>
              </h3>
              <p className="small muted">{layer.detail}</p>
              {layer.checks && layer.checks.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <CheckTable items={layer.checks} methods={checkMethods} />
                </div>
              )}
            </div>
          ))}

          {selfCheckItems.length > 0 && (
            <div style={{ marginTop: 18 }}>
              <h2>解析自检结果（S1–S7）</h2>
              <table className="grid compact">
                <thead><tr><th>代码</th><th>自检项</th><th>状态</th><th>详情</th></tr></thead>
                <tbody>
                  {selfCheckItems.map((sc, idx) => {
                    const b = checkStatusBadge(sc.status);
                    return (
                      <tr key={sc.code || idx}>
                        <td className="mono small">{sc.code}</td>
                        <td>{sc.name}</td>
                        <td><span className={b.cls}>{b.label}</span></td>
                        <td className="small muted">{sc.detail || '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {verification && Object.keys(verification).length > 0 && (
            <div className="verify-block" style={{ marginTop: 18 }}>
              <h3>慢通道复核状态</h3>
              <p className="small muted">
                <span className={verifyStatusMeta(verification.status).cls} style={{ marginRight: 8 }}>
                  {verifyStatusMeta(verification.status).label}
                </span>
                {(verification.checked_at || verification.verified_at) ? `时间：${verification.checked_at || verification.verified_at}` : ''}
                {typeof verification.txn_count_fast === 'number' ? ` · 快通道 ${verification.txn_count_fast} 笔` : ''}
                {typeof verification.txn_count_slow === 'number' ? ` · 慢通道 ${verification.txn_count_slow} 项` : ''}
                {typeof verification.diff_count === 'number' ? ` · 差异 ${verification.diff_count} 处` : ''}
                {verification.reason ? ` · 原因：${verification.reason}` : ''}
                {verification.summary ? ` · ${verification.summary}` : ''}
              </p>
              {verification.diffs?.length ? (
                <details style={{ marginTop: 8 }}>
                  <summary className="small">查看慢通道差异明细（{verification.diffs.length} 条）</summary>
                  <ul className="plain small" style={{ marginTop: 6 }}>
                    {verification.diffs.slice(0, 30).map((d, i) => (
                      <li key={i} className="mono">{typeof d === 'string' ? d : JSON.stringify(d)}</li>
                    ))}
                  </ul>
                </details>
              ) : null}
              {verification.notes?.length ? (
                <ul className="plain small">
                  {verification.notes.map((n, i) => <li key={i}>{n}</li>)}
                </ul>
              ) : null}
            </div>
          )}
        </section>
      ) : null}

      {tab === 'metrics' ? (
        <>
          {Object.entries(grouped).map(([domain, items]) => (
            <section key={domain}>
              <h2>
                {domain}（{items.filter((item) => item.value !== null).length}/{items.length} 有值）
              </h2>
              <table className="grid compact">
                <thead><tr><th>代号</th><th>指标</th><th>值</th><th>单位</th><th /></tr></thead>
                <tbody>
                  {items.map((metric) => {
                    const open = openMetric === metric.code;
                    return (
                      <Fragment key={metric.code}>
                        <tr className="metric-row" onClick={() => setOpenMetric(open ? null : metric.code)}>
                          <td className="mono small">{metric.code}</td>
                          <td>{metric.name}</td>
                          <td className={'mono ' + (metric.value === null ? 'muted' : '')}>{metric.value ?? '不可算'}</td>
                          <td className="small muted">{metric.unit}</td>
                          <td className="small muted">{open ? '收起' : '怎么看'}</td>
                        </tr>
                        {open ? (
                          <tr className="metric-detail">
                            <td colSpan={5}>
                              <MetricExplain
                                metric={metric}
                                def={metricDefs[metric.code]}
                                trend={report.trend}
                                txns={txns}
                                thresholdHint={metricThresholdHints[metric.code] ?? null}
                              />
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </section>
          ))}
        </>
      ) : null}

      {tab === 'evidence' ? (
        <>
          <section>
            <div className="panel-head">
              <h2>命中证据与原件定位（{report.evidence?.length ?? 0}）</h2>
              <Button size="sm" variant="ghost" onClick={() => void openOriginalAt(1)}>
                打开原件浏览第 1 页
              </Button>
            </div>
            {report.evidence?.length ? (
              <table className="grid compact">
                <thead><tr><th>规则</th><th>页码</th><th>笔号</th><th>页面坐标</th><th>追踪定位</th></tr></thead>
                <tbody>
                  {report.evidence.map((raw, index) => {
                    const item = (raw ?? {}) as { rule_code?: string; page_no?: number; txn_id?: number; x?: number; y?: number };
                    return (
                      <tr key={index}>
                        <td className="mono small">{item.rule_code ?? '—'}</td>
                        <td className="small muted">{item.page_no ?? '—'}</td>
                        <td className="small muted">{item.txn_id ?? '—'}</td>
                        <td className="small muted mono">
                          {item.x === undefined
                            ? '—'
                            : isNormalizedCoord(item.x, item.y ?? 0)
                              ? `${(item.x * 100).toFixed(1)}%, ${((item.y ?? 0) * 100).toFixed(1)}%`
                              : `${Math.round(item.x)}, ${Math.round(item.y ?? 0)} pt`}
                        </td>
                        <td className="actions-cell">
                          <button
                            type="button"
                            className="link-btn"
                            onClick={() =>
                              void openOriginalAt(item.page_no ?? 1, item.x, item.y, item.rule_code)
                            }
                          >
                            定位原件
                          </button>
                          {item.txn_id ? (
                            <button
                              type="button"
                              className="link-btn"
                              onClick={() => {
                                const rowNo = item.txn_id ?? null;
                                setHighlightRow(rowNo);
                                setKeyword('');
                                if (rowNo) setTxnPage(Math.floor((rowNo - 1) / PAGE));
                                setTab('txns');
                              }}
                            >
                              看明细行
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p className="muted small">这份报告没有独立的坐标级异常证据；可点右上角直接调阅原件 PDF。</p>
            )}
          </section>

          {drawerOpen && (
            <section className="evidence-viewer">
              <div className="ann-preview-head">
                <div>
                  <strong>原件调阅与坐标定位</strong>
                  <span className="small muted" style={{ marginLeft: 10 }}>
                    第 {docPageIdx + 1} / {docPageCount} 页
                    {marker?.label ? ` · 高亮规则：${marker.label}` : ''}
                  </span>
                </div>
                <div className="filters">
                  <button
                    type="button"
                    className="ann-btn"
                    disabled={docPageIdx <= 0}
                    onClick={() => setDocPageIdx((p) => Math.max(0, p - 1))}
                  >
                    ‹ 上一页
                  </button>
                  <button
                    type="button"
                    className="ann-btn"
                    disabled={docPageIdx >= docPageCount - 1}
                    onClick={() => setDocPageIdx((p) => Math.min(docPageCount - 1, p + 1))}
                  >
                    下一页 ›
                  </button>
                  <Button size="sm" variant="ghost" onClick={() => setDrawerOpen(false)}>关闭原件</Button>
                </div>
              </div>
              {needDocPassword && (
                <div className="import-box" style={{ marginBottom: 10 }}>
                  <strong>该原件受口令保护，请输入 PDF 打开口令以调阅：</strong>
                  {docPasswordWrong ? <span className="small" style={{ color: '#c0392b', marginLeft: 8 }}>口令不正确，请重试</span> : null}
                  <div className="try-row" style={{ marginTop: 8 }}>
                    <input
                      type="password"
                      placeholder="输入 PDF 打开口令"
                      value={docPasswordInput}
                      onChange={(e) => setDocPasswordInput(e.target.value)}
                    />
                    <Button
                      size="sm"
                      disabled={!docPasswordInput.trim()}
                      onClick={() => {
                        setDocPassword(docPasswordInput.trim());
                        setNeedDocPassword(false);
                        setDocPasswordWrong(false);
                        setDocRenderError('');
                      }}
                    >
                      解锁原件
                    </Button>
                  </div>
                </div>
              )}
              {docRenderError ? <Notice>{docRenderError}</Notice> : null}
              {fileLoading ? (
                <p className="muted">原件加载中…</p>
              ) : fileBytes ? (
                <div className="ann-stage-wrap" style={{ minHeight: 460 }}>
                  <PdfPageCanvas
                    fileBytes={fileBytes}
                    mimeHint={fileMime}
                    pageIndex={docPageIdx}
                    zoom={1.0}
                    password={docPassword || undefined}
                    onPasswordRequired={(wrong) => {
                      setNeedDocPassword(true);
                      setDocPasswordWrong(Boolean(wrong));
                    }}
                    onError={(msg) => setDocRenderError(msg)}
                    onPageInfo={(info) => {
                      setDocPageCount(info.pageCount || 1);
                      setDocBaseSize(info);
                      setNeedDocPassword(false);
                      setDocRenderError('');
                    }}
                    overlay={
                      marker &&
                      marker.page === docPageIdx &&
                      marker.x !== undefined &&
                      marker.y !== undefined &&
                      docBaseSize &&
                      docBaseSize.baseWidth > 0 ? (() => {
                        const norm = isNormalizedCoord(marker.x, marker.y);
                        const leftPct = norm ? marker.x * 100 : (marker.x / docBaseSize.baseWidth) * 100;
                        const topPct = norm ? marker.y * 100 : (marker.y / docBaseSize.baseHeight) * 100;
                        return (
                          <div className="ann-overlay" style={{ pointerEvents: 'none' }}>
                            <div
                              className="evidence-pin"
                              style={{
                                left: `${Math.max(0, Math.min(98, leftPct))}%`,
                                top: `${Math.max(0, Math.min(98, topPct))}%`,
                              }}
                            >
                              <span>{marker.label || '命中位置'}</span>
                            </div>
                          </div>
                        );
                      })() : null
                    }
                  />
                </div>
              ) : null}
            </section>
          )}

          <section>
            <h2>材料与文件指纹（{report.materials?.length ?? 0}）</h2>
            <table className="grid compact">
              <thead><tr><th>角色</th><th>页数</th><th>SHA-256 指纹</th></tr></thead>
              <tbody>
                {(report.materials ?? []).map((item, index) => (
                  <tr key={index}>
                    <td>{String(item.role)}</td>
                    <td>{String(item.pages)}</td>
                    <td className="small muted mono">{item.sha256 ? String(item.sha256).slice(0, 24) + '…' : '未记录'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      ) : null}

      {tab === 'txns' ? (
        <section>
          <div className="filters" style={{ marginBottom: 10 }}>
            <input
              className="search"
              placeholder="搜索摘要 / 对方户名 / 金额 / 日期"
              value={keyword}
              onChange={(event) => {
                setKeyword(event.target.value);
                setTxnPage(0);
              }}
            />
            <span className="muted small">
              {txns === null ? '加载中…' : `共 ${filteredTxns.length} 笔`}
            </span>
          </div>
          {txns && txns.length ? (
            <section>
              <h3>交易金额量级分布</h3>
              <AmountHistogram amounts={txns.filter((row) => row.amount).map((row) => Number(row.amount))} />
            </section>
          ) : null}

          <table className="grid compact">
            <thead>
              <tr><th>日期</th><th>方向</th><th>金额</th><th>余额</th><th>摘要</th><th>对方户名</th><th>页</th></tr>
            </thead>
            <tbody>
              {filteredTxns.slice(txnPage * PAGE, txnPage * PAGE + PAGE).map((row, offset) => (
                <tr
                  key={row.id}
                  ref={highlightRow === txnPage * PAGE + offset + 1 ? highlightRef : undefined}
                  className={highlightRow === txnPage * PAGE + offset + 1 ? 'active-row' : ''}
                >
                  <td className="small">{row.txn_date ?? '—'}</td>
                  <td className="small">{row.direction === 'in' ? '收入' : row.direction === 'out' ? '支出' : '—'}</td>
                  <td className="mono">{row.amount ?? '—'}</td>
                  <td className="small muted mono">{row.balance ?? '—'}</td>
                  <td className="small">{row.summary ?? ''}</td>
                  <td className="small muted">{row.counterparty_name ?? ''}</td>
                  <td className="small muted">{row.page_no ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filteredTxns.length > PAGE ? (
            <div className="pager">
              <button className="btn btn-ghost" disabled={txnPage === 0} onClick={() => setTxnPage(txnPage - 1)}>上一页</button>
              <span className="muted small">
                第 {txnPage * PAGE + 1}–{Math.min((txnPage + 1) * PAGE, filteredTxns.length)} 笔 / 共 {filteredTxns.length} 笔
              </span>
              <button
                className="btn btn-ghost"
                disabled={(txnPage + 1) * PAGE >= filteredTxns.length}
                onClick={() => setTxnPage(txnPage + 1)}
              >
                下一页
              </button>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
