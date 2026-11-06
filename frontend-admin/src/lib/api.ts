import { getToken, notifyAuthRequired } from './auth';

export interface PrereadInfo {
  verdict: string;
  is_statement: boolean; confidence: number;
  bank_name: string | null; bank_code: string | null;
  account_masked: string | null; holder_masked: string | null;
  period_start: string | null; period_end: string | null;
  pages: number; has_text_layer: boolean; text_chars: number;
  keyword_hits: string[]; irrelevant_hits: string[];
  txn_like_rows: number; amounts_found: number;
  sample_rows: string[]; reasons: string[];
}

export interface TaskRow {
  id: number; biz_no: string; status: string; carrier: string | null; created_at: string | null;
  check_result?: { preread?: PrereadInfo | null; warnings?: string[]; self_check?: unknown } | null;
}
export interface TrustLayer {
  layer: string; label: string; status: string; score: number; weight: number; note: string;
}

export interface TrustScore {
  score: number; level: string; label: string; carrier: string; note: string;
  layers: TrustLayer[];
}

export interface ReportPayload {
  carrier: string; verdict: string; verdict_reason: string;
  trust?: TrustScore | null;
  limitations: string[];
  layers: { layer: string; status: string; detail: string; checks: ReportCheck[] }[];
  self_check: ReportCheck[];
  metrics: { code: string; name: string; value: string | null; unit: string | null; note: string | null; caliber_version: number }[];
  metric_set_version: number; threshold_version: number;
  conclusions: { code: string; level: string; threshold: string; value: string }[];
  evidence: { txn_id: number | null; rule_code: string; page_no: number; x: number; y: number }[];
  materials: { file_id: number; role: string; pages: number | null; sha256: string | null }[];
  version: number;
  trend: { month: string; income: string; expense: string }[];
  scores?: {
    overall: number; grade: string; grade_label: string; method: string;
    domains: { key: string; name: string; weight: number; desc: string; score: number;
               metric_total: number; metric_valued: number; missing: number; hits: string[]; detail: string }[];
  } | null;
}

const BASE = '/api/v1';

function authFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers ?? {});
  const token = getToken();
  if (token) headers.set('Authorization', 'Bearer ' + token);
  return fetch(input, { ...init, headers });
}

async function json<T>(res: Response): Promise<T> {
  const data = await res.json().catch(() => null);
  if (res.status === 401 || res.status === 503) notifyAuthRequired();
  if (!res.ok) {
    const detail = data?.detail;
    const msg = typeof detail === 'string' ? detail : detail?.message || `请求失败（${res.status}）`;
    const code = typeof detail === 'object' ? detail?.code : undefined;
    throw Object.assign(new Error(msg), { code });
  }
  return data as T;
}

export interface TaskSummary {
  id: number; biz_no: string; status: string; carrier: string | null; created_at: string | null;
  bank_name: string | null; bank_code: string | null;
  period_start: string | null; period_end: string | null;
  verdict: string | null;
  authenticity: { level: string; label: string; blocked_layers: string[]; limited_layers: string[]; missing_materials?: string[] };
  parse: {
    level: string; label: string; txn_count: number;
    metrics_valued: number; metrics_total: number;
    failed_checks: string[]; limited_checks: string[];
  };
  risk: { level: string; label: string; count: number; hits: { code: string | null; level: string; value: string }[] };
  source: { level: string; label: string; file_status: string | null };
  income: string | null; monthly_income: string | null; dti: string | null; net_inflow: string | null;
  risk_codes: (string | null)[];
  materials: number; limitations: number; report_version: number | null;
}

export interface TaskFacets {
  authenticity: Record<string, number>;
  source: Record<string, number>;
  risk: Record<string, number>;
  parse: Record<string, number>;
  bank: Record<string, number>;
  total: number;
}

export interface TaskSummaryList { items: TaskSummary[]; total: number; offset?: number; limit?: number; facets: TaskFacets }

export interface TaskFilters {
  offset?: number;
  trash?: number;
  authenticity?: string;
  source?: string;
  risk?: string;
  risk_code?: string;
  parse?: string;
  bank?: string;
  date_from?: string;
  date_to?: string;
  q?: string;
  min_income?: number;
  max_income?: number;
  limit?: number;
}

export async function listTasks(filters: TaskFilters = {}): Promise<TaskSummaryList> {
  const params = new URLSearchParams();
  params.set('limit', String(filters.limit ?? 20));
  if (filters.offset) params.set('offset', String(filters.offset));
  for (const key of ['authenticity', 'source', 'risk', 'risk_code', 'parse', 'bank', 'date_from', 'date_to', 'q'] as const) {
    const value = filters[key];
    if (value) params.set(key, value);
  }
  if (filters.min_income !== undefined) params.set('min_income', String(filters.min_income));
  if (filters.max_income !== undefined) params.set('max_income', String(filters.max_income));
  if (filters.trash) params.set('trash', '1');
  return json<TaskSummaryList>(await authFetch(BASE + '/tasks?' + params.toString()));
}

export async function reanalyzeTask(taskId: number, password?: string): Promise<{ task_id: number; version: number }> {
  const form = new FormData();
  if (password) form.append('password', password);
  return json<{ task_id: number; version: number }>(await authFetch(BASE + '/tasks/' + taskId + '/reanalyze', {
    method: 'POST', body: form,
  }));
}

export interface FlowMergeMode { key: string; label: string; one_line: string; formula: string; when: string; caveat: string; level: string }
export interface FlowMergeAccount { account_id: string; bank_code: string | null; period_start: string | null; period_end: string | null; txn_count: number; inflow: string; outflow: string }
export interface FlowMergeTransfer { amount: string; from: string; to: string; out_date: string; in_date: string }
export interface FlowMergeResult {
  mode: string; label: string; formula: string; one_line: string;
  period_start: string | null; period_end: string | null; overlap_days: number;
  accounts: FlowMergeAccount[];
  raw_txn_count: number; txn_count: number; dropped_duplicates: number;
  internal_transfers: FlowMergeTransfer[];
  metrics: { code: string; name: string; value: string | null; basis: string }[];
  notes: string[];
}

export async function getReport(taskId: number): Promise<ReportPayload> {
  return json<ReportPayload>(await authFetch(`${BASE}/reports/${taskId}`));
}

export interface TxnRow {
  id: number; txn_date: string | null; direction: string | null;
  amount: string | null; balance: string | null; summary: string | null;
  counterparty_name?: string | null; page_no?: number | null; confidence?: string | null;
}

export async function getTransactions(taskId: number): Promise<TxnRow[]> {
  return json<TxnRow[]>(await authFetch(`${BASE}/tasks/${taskId}/transactions?limit=2000`));
}

export interface ReportCheck { code: string; name: string; status: string; detail: string }

export interface VerificationDef { code: string; layer: string; method: string }

export async function getVerificationDefinitions(): Promise<{ items: VerificationDef[] }> {
  return json<{ items: VerificationDef[] }>(await authFetch(BASE + '/verification-definitions'));
}

export interface MetricDef {
  code: string; name: string; unit: string; group: string;
  formula: string; inputs: string; viz: string;
}

export interface MetricDefs { metric_set_version: number; items: MetricDef[] }


export async function getThresholdDefinitions(): Promise<{ items: ThresholdDef[] }> {
  return json<{ items: ThresholdDef[] }>(await authFetch(BASE + '/thresholds/definitions'));
}

export async function getMetricDefinitions(): Promise<MetricDefs> {
  return json<MetricDefs>(await authFetch(BASE + '/metric-definitions'));
}

export async function getTask(taskId: number): Promise<TaskRow> {
  return json<TaskRow>(await authFetch(`${BASE}/tasks/${taskId}`));
}

export interface TemplateRow { id: number; bank_code: string; version: number; status: string; field_map: Record<string, unknown> }

export async function listTemplates(): Promise<TemplateRow[]> {
  return json<TemplateRow[]>(await authFetch(`${BASE}/templates`));
}

export async function publishTemplate(id: number): Promise<{ status: string }> {
  return json<{ status: string }>(await authFetch(`${BASE}/templates/${id}/publish`, { method: 'POST' }));
}



export interface InferRow { field: string; column: number | null; source: string; confidence: number; why: string }
export interface InferResult {
  bank_code: string;
  valid?: boolean;
  field_map: Record<string, string | number>;
  provenance: InferRow[];
  columns: { index: number; x0: number; x1: number; samples: string[] }[];
  warnings: string[];
  template_id?: number;
  saved_invalid?: boolean;
}

export async function inferTemplate(form: FormData): Promise<InferResult> {
  return json<InferResult>(await authFetch(BASE + '/templates/infer', { method: 'POST', body: form }));
}

export interface EntityAccount {
  key: string; bank_name: string | null; bank_code: string | null;
  account_masked: string | null; holders: Record<string, number>;
  tasks: number[]; period_start: string | null; period_end: string | null;
}

export interface EntitySubject {
  key: string; holder_masked: string | null; confidence: string;
  accounts: Record<string, number>; tasks: number[];
}

export interface EntityConflict {
  kind: string; severity: string; account_key: string; account_masked: string | null;
  bank_name: string | null; holders: string[]; tasks: number[]; message: string;
  resolved?: boolean;
  resolution?: { subject: string; action: string; note: string | null; at: string | null } | null;
}

export interface MergeMethod {
  id: string; label: string; short: string; detail: string; formula: string; assumption: string;
}

export interface MergeResult {
  subject: string;
  method: MergeMethod;
  overlap: { id: string; label: string; detail: string };
  accounts: { task_id: number; bank_name: string | null; account_masked: string | null; months: number;
             txn_count: number; balance_end: string | null; risk_hits: number; verdict: string | null }[];
  coverage: { months: number; overlap_months: string[]; from: string | null; to: string | null };
  metrics: { code: string; name: string; value: number | null; unit: string; how: string; note: string }[];
  risk: { level: string; hits: number; per_account: number[] };
  sync?: { months: number; sync_months: string[]; score: string; lambda: string; amplify_factor: string } | null;
  unsupported: { code: string; name: string; reason: string }[];
  warnings: string[];
  explain: { why_this_method: string; assumption: string; ratio_rule: string; balance_rule: string };
}

export interface EntitiesPayload {
  accounts: EntityAccount[]; subjects: EntitySubject[]; conflicts: EntityConflict[];
  summary: { accounts: number; subjects: number; multi_account_subjects: number; conflicts: number; pending_conflicts?: number };
}

export interface SubjectMergeMethod {
  id: string; label: string; short: string; detail: string; formula: string; assumption: string;
  question?: string; approach?: string; impact?: string; when_to_use?: string; tier?: 'primary' | 'advanced';
}

export interface SubjectMergeResult {
  subject: string;
  method: SubjectMergeMethod;
  overlap: { id: string; label: string; detail: string };
  accounts: { task_id: number; bank_name: string | null; account_masked: string | null; months: number;
             txn_count: number; balance_end: string | null; risk_hits: number; verdict: string | null }[];
  coverage: { months: number; overlap_months: string[]; from: string | null; to: string | null };
  metrics: { code: string; name: string; value: number | null; unit: string; how: string; note: string }[];
  risk: { level: string; hits: number; per_account: number[] };
  sync?: { months: number; sync_months: string[]; score: string; lambda: string; amplify_factor: string } | null;
  unsupported: { code: string; name: string; reason: string }[];
  warnings: string[];
  explain: { why_this_method: string; assumption: string; ratio_rule: string; balance_rule: string };
}

export async function getEntities(): Promise<EntitiesPayload> {
  return json<EntitiesPayload>(await authFetch(BASE + '/entities'));
}

export async function getMergeMethods(): Promise<{ methods: SubjectMergeMethod[]; overlap_modes: { id: string; label: string; detail: string }[] }> {
  return json(await authFetch(BASE + '/entities/methods'));
}

export async function mergeSubject(subject: string, method: string, overlap: string): Promise<SubjectMergeResult> {
  const params = new URLSearchParams({ subject, method, overlap });
  return json<SubjectMergeResult>(await authFetch(BASE + '/entities/merge?' + params.toString()));
}

export async function reanalyzeWithTemplate(taskId: number, templateId: number | null, password?: string): Promise<{ task_id: number; version: number }> {
  const form = new FormData();
  if (password) form.append('password', password);
  if (templateId !== null) form.append('template_id', String(templateId));
  return json<{ task_id: number; version: number }>(await authFetch(BASE + '/tasks/' + taskId + '/reanalyze', { method: 'POST', body: form }));
}

export async function whitelistTask(taskId: number, reason: string): Promise<{ task_id: number; whitelisted: boolean }> {
  const form = new FormData();
  form.append('reason', reason);
  return json<{ task_id: number; whitelisted: boolean }>(await authFetch(BASE + '/tasks/' + taskId + '/whitelist', { method: 'POST', body: form }));
}

export interface ThresholdDef {
  key: string; label: string; group: string; kind: string; unit: string;
  default: string | number | null; minimum: string | number | null; maximum: string | number | null;
  desc: string; impacts: string[]; calibrated: boolean;
}

export interface ThresholdPayload {
  version: number;
  values: Record<string, string | number | null>;
  defaults: Record<string, string | number | null>;
  defs: ThresholdDef[];
  history: { version: number; note: string | null; created_at: string | null;
    values: Record<string, string | number | null>;
    related_metrics?: { action: string; detail: string; at: string | null }[] }[];
}

export async function getThresholds(): Promise<ThresholdPayload> {
  return json<ThresholdPayload>(await authFetch(BASE + '/thresholds'));
}

export async function saveThresholds(values: Record<string, string | number | null>, note?: string): Promise<{ version: number; saved_version: number; values: Record<string, string | number | null> }> {
  return json(await authFetch(BASE + '/thresholds', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values, note: note ?? null }),
  }));
}

export async function resetThresholds(): Promise<{ version: number; values: Record<string, string | number | null> }> {
  return json(await authFetch(BASE + '/thresholds/reset', { method: 'POST' }));
}

export async function recycleTasks(taskIds: number[]): Promise<{ moved: number }> {
  return json(await authFetch(BASE + '/tasks/recycle', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_ids: taskIds }),
  }));
}

export async function restoreTasks(taskIds: number[]): Promise<{ restored: number }> {
  return json(await authFetch(BASE + '/tasks/restore', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_ids: taskIds }),
  }));
}

export async function purgeTasks(taskIds: number[]): Promise<{ purged: number }> {
  return json(await authFetch(BASE + '/tasks/purge', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_ids: taskIds, confirm: true }),
  }));
}

export async function downloadAttachment(path: string, fallbackName: string): Promise<void> {
  const res = await authFetch(BASE + path);
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail?.message || ('导出失败（' + res.status + '）'));
  }
  const disposition = res.headers.get('Content-Disposition') || '';
  const match = /filename=([^;]+)/.exec(disposition);
  const name = match ? match[1].trim() : fallbackName;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export interface TemplateStats {
  template_id: number; bank_code: string; version: number; status: string;
  tasks_total: number; tasks_done: number; tasks_failed: number;
  success_rate: number | null; avg_txn_count: number | null; zero_txn_tasks: number;
}

export interface TemplatePreview {
  template_id: number; txn_count: number; page_count: number; warnings: string[];
  rows: { txn_date: string | null; summary: string | null; direction: string | null;
          amount: string | null; balance: string | null; page_no: number }[];
}

export async function updateTemplate(id: number, patch: { bank_code?: string; field_map?: Record<string, unknown>; header_columns?: unknown[] }): Promise<{ id: number; version: number }> {
  return json(await authFetch(BASE + '/templates/' + id, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
  }));
}

export async function duplicateTemplate(id: number): Promise<{ id: number; version: number }> {
  return json(await authFetch(BASE + '/templates/' + id + '/duplicate', { method: 'POST' }));
}

export async function disableTemplate(id: number): Promise<{ id: number; status: string }> {
  return json(await authFetch(BASE + '/templates/' + id + '/disable', { method: 'POST' }));
}

export interface DeleteTemplateResult { deleted: number; soft: boolean; used: number; message: string }

export async function deleteTemplate(id: number): Promise<DeleteTemplateResult> {
  return json(await authFetch(BASE + '/templates/' + id, { method: 'DELETE' }));
}

export async function templateStats(id: number): Promise<TemplateStats> {
  return json(await authFetch(BASE + '/templates/' + id + '/stats'));
}

export async function previewTemplate(id: number, file: File, password?: string): Promise<TemplatePreview> {
  const form = new FormData();
  form.append('file', file);
  if (password) form.append('password', password);
  return json(await authFetch(BASE + '/templates/' + id + '/preview', { method: 'POST', body: form }));
}

export async function importTemplate(payload: { bank_code: string; field_map: Record<string, unknown>; header_columns?: unknown[] }): Promise<{ id: number; version: number }> {
  return json(await authFetch(BASE + '/templates/import', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }));
}

export interface TemplateLayoutBox { field: string; column: string; page: number; x0: number; y0: number; x1: number; y1: number }
export interface TemplateLayoutPayload {
  template_id: number; has_sample: boolean;
  layout: { pages: Record<string, { width: number; height: number }>; page_count: number; boxes: TemplateLayoutBox[] } | null;
  field_map: Record<string, unknown> | null;
  header_columns: string[] | null;
}

export async function getTemplateLayout(id: number): Promise<TemplateLayoutPayload> {
  return json<TemplateLayoutPayload>(await authFetch(BASE + '/templates/' + id + '/layout'));
}

export async function getTemplateLayoutPng(id: number, page = 0): Promise<Blob> {
  const res = await authFetch(BASE + '/templates/' + id + '/layout.png?page=' + page);
  if (!res.ok) throw new Error('没有可回看的样本');
  return await res.blob();
}

export interface ProbeSuggestion { field: string; column: string; x: number; y: number }
export interface ProbeResult {
  bank_name: string | null;
  bank_code: string | null;
  rotation: number;
  page_size: { width: number; height: number };
  header_found: boolean;
  headers: { text: string; x: number; y: number; x0?: number; x1?: number; top?: number; bottom?: number }[];
  boundaries?: { after: string; before: string; gap: number; x: number }[];
  table_area?: { x: number; y: number; w: number; h: number; header_y?: number } | null;
  suggestions: ProbeSuggestion[];
  meta: Record<string, { value: string; rect: { x: number; y: number; w: number; h: number } | null }>;
}

export async function probeTemplate(form: FormData): Promise<ProbeResult> {
  const res = await authFetch(BASE + '/templates/probe', { method: 'POST', body: form });
  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.json();
      detail = typeof body?.detail === 'string' ? body.detail : (body?.detail?.message || '');
    } catch { /* ignore */ }
    throw new Error('HTTP ' + res.status + (detail ? '：' + detail : ''));
  }
  return (await res.json()) as ProbeResult;
}

export async function decryptPdf(file: File, password: string): Promise<Blob> {
  const form = new FormData();
  form.append('file', file);
  form.append('password', password);
  const res = await authFetch(BASE + '/templates/decrypt', { method: 'POST', body: form });
  if (!res.ok) throw new Error('解密失败（口令可能不正确）');
  return await res.blob();
}

export type AuditLogRow = {
  id: number;
  actor_id: number | null;
  action: string;
  object_type: string | null;
  object_id: number | null;
  detail: string | null;
  created_at: string | null;
};

export type AuditLogPage = { total: number; page: number; size: number; items: AuditLogRow[] };

/** 审计日志（只读）：按动作与分页筛选。 */
export async function listAuditLogs(params: { page?: number; size?: number; action?: string } = {}): Promise<AuditLogPage> {
  const q = new URLSearchParams();
  q.set('page', String(params.page ?? 1));
  q.set('size', String(params.size ?? 30));
  if (params.action) q.set('action', params.action);
  return json<AuditLogPage>(await authFetch(BASE + '/audit?' + q.toString()));
}

export type AppUserRow = {
  id: number;
  username: string;
  role: string;
  display_name?: string | null;
  status?: string;
  created_at?: string | null;
};

/** 账号列表（银行侧）。 */
export async function listUsers(): Promise<{ items: AppUserRow[] }> {
  return json<{ items: AppUserRow[] }>(await authFetch(BASE + '/auth/users'));
}

export type DashboardData = {
  summary: {
    tasks: number; done: number; failed: number; txn_total: number;
    avg_txn: number; coverage_warn: number; threshold_version: number | null; custom_metrics?: number;
  };
  grades: { grade: string; label: string; count: number }[];
  verdicts: { verdict: string; count: number }[];
  banks: { bank_code: string; tasks: number; txn: number }[];
  threshold_hits: { code: string; name: string; count: number; threshold_key: string | null }[];
  recent: {
    task_id: number; biz_no: string | null; status: string; bank_code: string | null;
    verdict: string | null; overall: number | null; grade: string | null; txn_count: number;
  }[];
};

/** 业务看板：库里已有流水的汇总。 */
export async function getDashboard(): Promise<DashboardData> {
  return json<DashboardData>(await authFetch(BASE + '/dashboard'));
}

export type CustomMetric = {
  id: number; code: string; name: string; unit?: string | null;
  group_name?: string | null; formula?: string | null; inputs?: string | null;
  note?: string | null; enabled: boolean; created_at?: string | null;
};

export async function listCustomMetrics(): Promise<{ items: CustomMetric[]; note: string }> {
  return json<{ items: CustomMetric[]; note: string }>(await authFetch(BASE + '/custom-metrics'));
}

export async function createCustomMetric(payload: {
  code: string; name: string; unit?: string; group_name?: string;
  formula?: string; inputs?: string; note?: string;
}): Promise<CustomMetric> {
  return json<CustomMetric>(await authFetch(BASE + '/custom-metrics', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }));
}

export async function deleteCustomMetric(id: number): Promise<{ ok: boolean }> {
  return json<{ ok: boolean }>(await authFetch(BASE + '/custom-metrics/' + id, { method: 'DELETE' }));
}

/** 用一份临时标注直接解析一份流水：标注只随本次任务生效，不写回模板库。 */
export async function createTaskWithTempTemplate(
  file: File, marks: unknown[], bankCode?: string, password?: string,
): Promise<{ task_id: number; status: string; biz_no?: string }> {
  const form = new FormData();
  form.append('file', file);
  form.append('marks', JSON.stringify(marks));
  if (bankCode) form.append('bank_code', bankCode);
  if (password) form.append('password', password);
  return json<{ task_id: number; status: string; biz_no?: string }>(
    await authFetch(BASE + '/tasks', { method: 'POST', body: form }),
  );
}

/** 人工确认「这个账号实际属于哪个户名」，会写审计。 */
export async function resolveConflict(accountKey: string, subject: string, note?: string): Promise<{ ok: boolean }> {
  return json<{ ok: boolean }>(await authFetch(BASE + '/entities/conflicts/resolve', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account_key: accountKey, subject, note }),
  }));
}

export async function undoConflict(accountKey: string): Promise<{ ok: boolean }> {
  return json<{ ok: boolean }>(await authFetch(
    BASE + '/entities/conflicts/resolve?account_key=' + encodeURIComponent(accountKey),
    { method: 'DELETE' },
  ));
}

/** 用一次性标注把某个任务重新解析（临时模板：用完即弃，不进模板库）。 */
export async function reparseTask(taskId: number, marks: unknown[]): Promise<{ task_id: number; status: string; mode: string }> {
  const form = new FormData();
  form.append('marks', JSON.stringify(marks));
  return json<{ task_id: number; status: string; mode: string }>(
    await authFetch(BASE + '/tasks/' + taskId + '/reparse', { method: 'POST', body: form }),
  );
}

/** 取任务原始文件，用于在标注页直接重解析（不必让用户重新选文件）。 */
export async function getTaskFile(taskId: number): Promise<File> {
  const res = await authFetch(BASE + '/tasks/' + taskId + '/file');
  if (!res.ok) throw new Error('取原始文件失败（HTTP ' + res.status + '）');
  const blob = await res.blob();
  const name = 'task-' + taskId + (blob.type.includes('pdf') ? '.pdf' : '.jpg');
  return new File([blob], name, { type: blob.type || 'application/pdf' });
}

/** 取模板样本文件（改框画范围时回看用同一份样本）。 */
export async function getTemplateSample(templateId: number): Promise<File> {
  const res = await authFetch(BASE + '/templates/' + templateId + '/sample');
  if (!res.ok) throw new Error('这个模板没有保存样本文件');
  const blob = await res.blob();
  return new File([blob], 'template-' + templateId + (blob.type.includes('pdf') ? '.pdf' : '.jpg'),
    { type: blob.type || 'application/pdf' });
}

/** 保存模板的框画范围（会生成新版本草稿）。 */
export async function saveTemplateLayout(templateId: number, layout: unknown, fieldMap: unknown): Promise<{
  id: number; version: number; status: string; previous_id: number;
}> {
  return json(await authFetch(BASE + '/templates/' + templateId, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ layout, field_map: fieldMap }),
  }));
}

export async function getTemplateById(templateId: number): Promise<{
  id: number; bank_code: string; version: number; status: string;
  field_map: Record<string, unknown>; layout: unknown | null;
}> {
  return json(await authFetch(BASE + '/templates/' + templateId));
}