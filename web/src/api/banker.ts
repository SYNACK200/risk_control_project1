import { request, requestBlob, requestBlobWithMeta } from './client';

/** 银行侧接口直出对象（没有 {code,data} 信封），与借款侧不同——合并前端时这一点最容易踩。 */

export type TaskSummary = {
  id: number;
  biz_no: string;
  status: string;
  carrier: string | null;
  created_at: string | null;
  bank_name: string | null;
  bank_code: string | null;
  period_start: string | null;
  period_end: string | null;
  verdict: string | null;
  authenticity: { level: string; label: string };
  parse: { level: string; label: string; txn_count: number; metrics_valued: number; metrics_total: number };
  risk: { level: string; label: string; count: number };
  source: { level: string; label: string };
  income: string | null;
  monthly_income: string | null;
  dti: string | null;
  materials: number;
  limitations: number;
  report_version: number | null;
};

export type TaskList = { items: TaskSummary[]; total: number; facets: Record<string, Record<string, number>> };

export type TaskFilters = {
  q?: string;
  authenticity?: string;
  source?: string;
  status?: string;
  bank?: string;
  risk?: string;
  risk_code?: string;
  parse?: string;
  date_from?: string;
  date_to?: string;
  min_income?: string | number;
  max_income?: string | number;
  trash?: boolean;
  limit?: number;
  offset?: number;
};

export function listTasks(filters: TaskFilters = {}): Promise<TaskList> {
  const params = new URLSearchParams();
  params.set('limit', String(filters.limit ?? 20));
  if (filters.offset) params.set('offset', String(filters.offset));
  if (filters.q) params.set('q', filters.q);
  if (filters.authenticity) params.set('authenticity', filters.authenticity);
  if (filters.source) params.set('source', filters.source);
  if (filters.status) params.set('status', filters.status);
  if (filters.bank) params.set('bank', filters.bank);
  if (filters.risk) params.set('risk', filters.risk);
  if (filters.risk_code) params.set('risk_code', filters.risk_code);
  if (filters.parse) params.set('parse', filters.parse);
  if (filters.date_from) params.set('date_from', filters.date_from);
  if (filters.date_to) params.set('date_to', filters.date_to);
  if (filters.min_income !== undefined && filters.min_income !== '') params.set('min_income', String(filters.min_income));
  if (filters.max_income !== undefined && filters.max_income !== '') params.set('max_income', String(filters.max_income));
  if (filters.trash) params.set('trash', '1');
  return request<TaskList>('/tasks?' + params.toString());
}

export function reanalyzeTask(
  taskId: number,
  opts: { password?: string; templateId?: number } = {},
): Promise<{ task_id: number; status: string; queued: boolean; mode: string }> {
  const form = new FormData();
  if (opts.password) form.append('password', opts.password);
  if (opts.templateId !== undefined) form.append('template_id', String(opts.templateId));
  return request('/tasks/' + taskId + '/reanalyze', { form, timeoutMs: 120000 });
}

export function verifyTask(taskId: number): Promise<Record<string, unknown>> {
  return request('/tasks/' + taskId + '/verify', { method: 'POST', timeoutMs: 180000 });
}

export function whitelistTask(taskId: number, reason: string): Promise<{ task_id: number; whitelisted: boolean }> {
  const form = new FormData();
  form.append('reason', reason);
  return request('/tasks/' + taskId + '/whitelist', { form });
}

export function reparseTaskCanvas(
  taskId: number,
  payload: { fieldMap: Record<string, unknown>; layout: unknown; bankCode?: string },
): Promise<{ task_id: number; status: string; mode: string }> {
  const form = new FormData();
  form.append('field_map', JSON.stringify(payload.fieldMap));
  form.append('layout', JSON.stringify(payload.layout));
  if (payload.bankCode) form.append('bank_code', payload.bankCode);
  return request('/tasks/' + taskId + '/reparse', { form, timeoutMs: 120000 });
}

export function recycleTasks(taskIds: number[]): Promise<{ moved: number; ids: number[] }> {
  return request('/tasks/recycle', { body: { task_ids: taskIds } });
}

export function restoreTasks(taskIds: number[]): Promise<{ restored: number; ids: number[] }> {
  return request('/tasks/restore', { body: { task_ids: taskIds } });
}

export function purgeTasks(taskIds: number[]): Promise<{ purged: number; ids: number[] }> {
  return request('/tasks/purge', { body: { task_ids: taskIds, confirm: true } });
}

export function getTaskExportWithMeta(taskId: number, format: 'json' | 'csv'): Promise<{ blob: Blob; filename: string | null }> {
  return requestBlobWithMeta(format === 'json' ? `/tasks/${taskId}/export.json` : `/tasks/${taskId}/transactions.csv`);
}

export function getTaskExportBlob(taskId: number, format: 'json' | 'csv'): Promise<Blob> {
  return requestBlob(format === 'json' ? `/tasks/${taskId}/export.json` : `/tasks/${taskId}/transactions.csv`);
}

export function exportPrintableReport(taskId: number): Promise<{ blob: Blob; filename: string | null }> {
  return requestBlobWithMeta(`/reports/${taskId}/export`, { method: 'POST' });
}

export type ApprovalRecordItem = {
  id: number;
  report_id: number | null;
  report_version: number;
  decision: 'approve' | 'reject' | 'supplement' | 'hold';
  comment: string;
  actor_name: string;
  created_at: string | null;
};

export type TaskBankDetail = {
  id: number;
  biz_no: string;
  status: string;
  carrier: string | null;
  period_start: string | null;
  period_end: string | null;
  failure_code?: string | null;
  consent_version?: string | null;
  consent_at?: string | null;
  created_at?: string | null;
  check_result?: {
    preread?: Record<string, unknown>;
    header_meta?: Record<string, unknown>;
    matched_template?: { id?: number; bank_code?: string; version?: number; by?: string; score?: number } | null;
    template_match?: { template_id?: number | null; by?: string | null; score?: number | null; reason?: string | null };
    template_mismatch?: { reasons?: string[] } | null;
    whitelist?: { reason?: string; at?: string } | null;
    [key: string]: unknown;
  } | null;
};

export function getBankTask(taskId: number): Promise<TaskBankDetail> {
  return request<TaskBankDetail>('/tasks/' + taskId);
}

export function createApproval(
  taskId: number,
  payload: { decision: 'approve' | 'reject' | 'supplement' | 'hold'; comment: string },
): Promise<ApprovalRecordItem> {
  return request<ApprovalRecordItem>(`/reports/${taskId}/approvals`, { body: payload });
}

export type ReportPayload = {
  verdict: string;
  verdict_reason: string;
  carrier?: string;
  layers?: { layer: string; status: string; detail: string }[];
  metrics?: { code: string; name: string; value: string | null; unit: string; note: string; caliber_version?: number }[];
  scores?: {
    overall?: number;
    grade?: string;
    grade_label?: string;
    method?: string;
    domains?: {
      key: string;
      name: string;
      desc: string;
      score: number;
      weight: number;
      hits: string[];
      detail?: string;
      missing: number;
      metric_total: number;
      metric_valued: number;
    }[];
  };
  trend?: { month: string; income: string; expense: string }[];
  limitations?: string[];
  trust?: {
    score?: number;
    level?: string;
    label?: string;
    note?: string;
    layers?: { layer: string; label: string; score: number; weight: number; status: string; note?: string }[];
  };
  metric_set_version?: number;
  threshold_version?: number;
  conclusions?: { code: string; message: string; level: string; threshold?: string | number | null; value?: string | number | null }[];
  scores_detail?: unknown;
  evidence?: {
    rule_code?: string;
    page_no?: number;
    txn_id?: number;
    x?: number;
    y?: number;
  }[];
  materials?: { role: string; pages: number; sha256?: string | null; file_id?: number }[];
  self_check?: Record<string, unknown> | null;
  verification?: unknown;
  custom_field_stats?: unknown;
  header_meta?: Record<string, unknown>;
  approvals?: ApprovalRecordItem[];
  version?: number;
};

export function getReport(taskId: number): Promise<ReportPayload> {
  return request<ReportPayload>('/reports/' + taskId);
}

export type TxnRow = {
  id: number;
  txn_date: string | null;
  direction: string | null;
  amount: string | null;
  balance: string | null;
  summary: string | null;
  counterparty_name?: string | null;
  page_no?: number | null;
  confidence?: string | null;
};

export function getTransactions(taskId: number): Promise<TxnRow[]> {
  return request<TxnRow[]>('/tasks/' + taskId + '/transactions?limit=2000');
}

/** 取任务原件（PDF / 图片原始字节）；报告里的「原始文件」与「证据定位」就是它。 */
export function getTaskFile(taskId: number): Promise<Blob> {
  return requestBlob('/tasks/' + taskId + '/file');
}

export type DashboardData = {
  summary: {
    tasks: number;
    done: number;
    failed: number;
    txn_total: number;
    avg_txn: number;
    coverage_warn: number;
    threshold_version: number;
    custom_metrics: number;
  };
  verdicts: { verdict: string; count: number }[];
  grades: { grade: string; label: string; count: number }[];
  banks: { bank_code: string; tasks: number; txn: number }[];
  threshold_hits: { code: string; name: string; count: number; threshold_key: string | null }[];
  recent: {
    task_id: number;
    biz_no: string;
    status: string;
    bank_code: string | null;
    verdict: string | null;
    overall: number | null;
    grade: string | null;
    txn_count: number;
  }[];
};

export function getDashboard(): Promise<DashboardData> {
  return request<DashboardData>('/dashboard');
}

export type AuditRow = {
  id: number;
  actor_id: number | null;
  action: string;
  object_type: string | null;
  object_id: number | null;
  detail: string | null;
  created_at: string | null;
};

export function listAudit(params: { page?: number; size?: number; action?: string } = {}): Promise<{ items: AuditRow[]; total: number; page?: number; size?: number }> {
  const query = new URLSearchParams();
  query.set('page', String(params.page ?? 1));
  query.set('size', String(params.size ?? 20));
  if (params.action) query.set('action', params.action);
  return request('/audit?' + query.toString());
}

export type MetricDef = {
  code: string;
  name: string;
  unit: string;
  group: string;
  formula: string;
  inputs: string;
  viz: string;
};

export function getMetricDefinitions(): Promise<{ metric_set_version: number; items: MetricDef[] }> {
  return request<{ metric_set_version: number; items: MetricDef[] }>('/metric-definitions');
}

export type VerificationDef = { code: string; layer: string; method: string };

export function getVerificationDefinitions(): Promise<{ items: VerificationDef[] }> {
  return request<{ items: VerificationDef[] }>('/verification-definitions');
}

export type TemplateRow = {
  id: number;
  bank_code: string;
  version: number;
  status: string;
  field_map: Record<string, unknown>;
  header_columns?: string[] | null;
  required_fields?: string[] | null;
  has_layout?: boolean;
  has_sample?: boolean;
  tasks_total?: number;
  success_rate?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  deleted_at?: string | null;
};

export function listTemplates(includeDeleted = false, bankCode?: string): Promise<TemplateRow[]> {
  const params = new URLSearchParams();
  if (includeDeleted) params.set('include_deleted', 'true');
  if (bankCode) params.set('bank_code', bankCode);
  const qs = params.toString();
  return request<TemplateRow[]>('/templates' + (qs ? '?' + qs : ''));
}

export type TemplateDetail = {
  id: number;
  bank_code: string;
  version: number;
  status: string;
  field_map: Record<string, unknown>;
  header_columns?: string[] | null;
  layout: unknown | null;
  required_fields?: string[] | null;
  sample_file_id?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export function getTemplate(id: number): Promise<TemplateDetail> {
  return request<TemplateDetail>('/templates/' + id);
}

export type TemplateStats = {
  template_id: number;
  bank_code: string;
  version: number;
  status: string;
  tasks_total: number;
  tasks_done: number;
  tasks_failed: number;
  success_rate: number | null;
  avg_txn_count: number | null;
  zero_txn_tasks: number;
};

export function getTemplateStats(id: number): Promise<TemplateStats> {
  return request<TemplateStats>('/templates/' + id + '/stats');
}

export type TemplateLayoutBox = { field: string; column: string; page: number; x0: number; y0: number; x1: number; y1: number };
export type TemplateLayout = {
  template_id: number;
  has_sample: boolean;
  layout: {
    pages?: Record<string, { width: number; height: number }>;
    page_count?: number;
    boxes?: TemplateLayoutBox[];
    /** 模板真实页面尺寸（pt）：旧版 boxes 回看用它换算，别硬退 595×842 */
    page_size?: { w?: number; h?: number };
  } | null;
  field_map: Record<string, unknown> | null;
  header_columns: string[] | null;
};

export type TemplatePreview = {
  template_id: number | null;
  txn_count: number;
  page_count: number;
  pages: { page_no: number; rows: number; header_found: boolean; columns: number }[];
  warnings: string[];
  rows: {
    txn_date: string | null;
    summary: string | null;
    counterparty?: string | null;
    reference_no?: string | null;
    direction: string | null;
    amount: string | null;
    balance: string | null;
    page_no: number;
    extra?: Record<string, string> | null;
  }[];
  meta?: {
    account_no?: string | null;
    account_name?: string | null;
    bank_branch?: string | null;
    account_type?: string | null;
    currency?: string | null;
    period_start?: string | null;
    period_end?: string | null;
    [key: string]: string | null | undefined;
  };
  extra_meta?: Record<string, string>;
  required_fields: string[];
  missing_columns: string[];
  empty_columns: string[];
  present_columns: string[];
};

export function previewDraftTemplate(payload: {
  file: Blob;
  fileName?: string;
  bankCode: string;
  fieldMap: Record<string, unknown>;
  layout: unknown;
  requiredFields?: string[];
  password?: string;
}): Promise<TemplatePreview> {
  const form = new FormData();
  form.append('file', payload.file, payload.fileName || 'sample.pdf');
  form.append('bank_code', payload.bankCode);
  form.append('field_map', JSON.stringify(payload.fieldMap));
  form.append('layout', JSON.stringify(payload.layout));
  form.append('required_fields', JSON.stringify(payload.requiredFields ?? []));
  if (payload.password) form.append('password', payload.password);
  return request<TemplatePreview>('/templates/preview-draft', { form, timeoutMs: 240000 });
}

export function saveTemplateFromCanvas(payload: {
  bankCode: string;
  fieldMap: Record<string, unknown>;
  layout: unknown;
  requiredFields?: string[];
  templateId?: number | null;
  publish?: boolean;
  file?: Blob | null;
  fileName?: string;
}): Promise<{ id: number; bank_code: string; version: number; status: string; has_sample: boolean }> {
  const form = new FormData();
  form.append('bank_code', payload.bankCode);
  form.append('field_map', JSON.stringify(payload.fieldMap));
  form.append('layout', JSON.stringify(payload.layout));
  form.append('required_fields', JSON.stringify(payload.requiredFields ?? []));
  form.append('publish', String(Boolean(payload.publish)));
  if (payload.templateId != null) form.append('template_id', String(payload.templateId));
  if (payload.file) form.append('file', payload.file, payload.fileName || 'sample.pdf');
  return request('/templates/save-from-canvas', { form, timeoutMs: 120000 });
}

export function getTemplateSample(id: number): Promise<Blob> {
  return requestBlob('/templates/' + id + '/sample');
}

export function getTemplateLayoutPng(id: number, page = 0): Promise<Blob> {
  return requestBlob('/templates/' + id + '/layout.png?page=' + page);
}

export function exportTemplateBlob(id: number): Promise<Blob> {
  return requestBlob('/templates/' + id + '/export');
}

export function importTemplate(
  payload: Record<string, unknown> | Record<string, unknown>[],
): Promise<{ id: number; version: number; bank_code: string; status?: string; count?: number; items?: { id: number; version: number; bank_code: string; status: string }[] }> {
  return request('/templates/import', { body: payload });
}

export type ShortFieldSpec = {
  field: string;
  label: string;
  keywords: string;
};

export type HeaderFieldSpec = {
  field: string;
  label: string;
  keywords: string;
};

export type ShortFieldMatch = {
  field: string;
  label: string;
  keywords: string[];
  matched: boolean;
  anchor_text: string | null;
  value: string | null;
  page: number;
  rect: { x: number; y: number; w: number; h: number } | null;
  method: 'inline' | 'right_neighbor' | 'below_neighbor' | null;
  confidence: number;
};

export type HeaderFieldMatch = {
  field: string;
  label: string;
  keywords: string[];
  matched: boolean;
  header_text: string | null;
  x: number | null;
  w: number | null;
  sample_values: string[];
  hit_rows: number;
  confidence: number;
};

export type TemplateAnalyzeResult = {
  bank_code: string;
  bank_name: string | null;
  page_count: number;
  page_size: { w: number; h: number };
  ocr_used?: boolean;
  engine?: string;
  header_found: boolean;
  short_results: ShortFieldMatch[];
  header_results: HeaderFieldMatch[];
  table_area: { x: number; y: number; w: number; h: number; headerY: number } | null;
  preview_rows: { page_no: number; cells: Record<string, string> }[];
  field_map: Record<string, string>;
  layout: Record<string, unknown>;
  saved_template?: {
    id: number;
    bank_code: string;
    version: number;
    status: string;
    has_sample: boolean;
  };
};

export function analyzeTemplateFields(payload: {
  file: Blob;
  fileName?: string;
  shortFields: ShortFieldSpec[];
  headerFields: HeaderFieldSpec[];
  bankCode?: string;
  password?: string;
  save?: boolean;
  publish?: boolean;
}): Promise<TemplateAnalyzeResult> {
  const form = new FormData();
  const fname = payload.fileName || (payload.file instanceof File ? payload.file.name : 'sample.pdf');
  form.append('file', payload.file, fname);
  form.append('short_fields', JSON.stringify(payload.shortFields));
  form.append('header_fields', JSON.stringify(payload.headerFields));
  if (payload.bankCode?.trim()) form.append('bank_code', payload.bankCode.trim().toUpperCase());
  if (payload.password) form.append('password', payload.password);
  form.append('save', String(Boolean(payload.save)));
  form.append('publish', String(Boolean(payload.publish)));
  return request<TemplateAnalyzeResult>('/templates/analyze-fields', { form, timeoutMs: 180000 });
}

export function loadBuiltinTemplates(
  publish = false,
  force = false,
): Promise<{ loaded: { id: number; bank_code: string; version: number; status: string }[]; skipped: string[] }> {
  return request(`/templates/load-builtin?publish=${publish ? 'true' : 'false'}&force=${force ? 'true' : 'false'}`, {
    method: 'POST',
  });
}

export function previewTemplate(id: number, file: Blob, password?: string): Promise<TemplatePreview> {
  const form = new FormData();
  form.append('file', file, 'sample.pdf');
  if (password) form.append('password', password);
  return request<TemplatePreview>('/templates/' + id + '/preview', { form, timeoutMs: 240000 });
}

export function updateTemplateRequired(id: number, required: string[]): Promise<{ id: number; version: number }> {
  return request<{ id: number; version: number }>('/templates/' + id, {
    method: 'PUT',
    body: { required_fields: required },
  });
}

export function getTemplateLayout(id: number): Promise<TemplateLayout> {
  return request<TemplateLayout>('/templates/' + id + '/layout');
}

export function publishTemplate(id: number): Promise<{ status: string }> {
  return request<{ status: string }>('/templates/' + id + '/publish', { method: 'POST' });
}

export function disableTemplate(id: number): Promise<{ status: string }> {
  return request<{ status: string }>('/templates/' + id + '/disable', { method: 'POST' });
}

export function duplicateTemplate(id: number): Promise<{ id: number; version: number }> {
  return request<{ id: number; version: number }>('/templates/' + id + '/duplicate', { method: 'POST' });
}

export function deleteTemplate(id: number): Promise<{ id: number; removed: boolean }> {
  return request<{ id: number; removed: boolean }>('/templates/' + id, { method: 'DELETE' });
}

export function restoreTemplate(id: number): Promise<{ id: number; restored: boolean }> {
  return request<{ id: number; restored: boolean }>('/templates/' + id + '/restore', { method: 'POST' });
}

export type ProbeSuggestion = { field: string; column: string; x: number; y: number; x0?: number; x1?: number; col_x?: number; col_w?: number };
export type ProbeResult = {
  bank_name: string | null;
  bank_code: string | null;
  rotation: number;
  page_size: { width: number; height: number };
  header_found: boolean;
  headers: { text: string; x: number; y: number }[];
  suggestions?: ProbeSuggestion[];
  table_area?: { x: number; y: number; w: number; h: number; header_y?: number } | null;
};

export function probeTemplate(file: File, password?: string): Promise<ProbeResult> {
  const form = new FormData();
  form.append('file', file);
  if (password) form.append('password', password);
  return request<ProbeResult>('/templates/probe', { form, timeoutMs: 180000 });
}

export function createTemplate(payload: { bank_code: string; field_map: Record<string, unknown> }): Promise<{ id: number; status: string }> {
  return request<{ id: number; status: string }>('/templates', { body: payload });
}

export function updateTemplate(
  id: number,
  patch: { field_map?: Record<string, unknown>; layout?: unknown },
): Promise<{ id: number; version: number }> {
  return request<{ id: number; version: number }>('/templates/' + id, { method: 'PUT', body: patch });
}

export type ThresholdDef = {
  key: string;
  label: string;
  group: string;
  kind: string;
  unit: string;
  default: string | number | null;
  minimum: string | number | null;
  maximum: string | number | null;
  desc: string;
  impacts: string[];
  calibrated: boolean;
};

export type ThresholdHistoryItem = {
  version: number;
  note?: string | null;
  created_at?: string | null;
  related_metrics?: string[];
};

export type ThresholdPayload = {
  version: number;
  values: Record<string, string | number | null>;
  defaults?: Record<string, string | number | null>;
  history?: ThresholdHistoryItem[];
  defs: ThresholdDef[];
};

export function getThresholds(): Promise<ThresholdPayload> {
  return request<ThresholdPayload>('/thresholds');
}

export function saveThresholds(
  values: Record<string, string | number | null>,
  note?: string,
): Promise<{ version: number; saved_version: number; values: Record<string, string | number | null> }> {
  return request('/thresholds', { method: 'PUT', body: { values, note } });
}

export function resetThresholds(): Promise<{ saved_version: number; values: Record<string, string | number | null> }> {
  return request('/thresholds/reset', { method: 'POST' });
}

export type MetricAtom = {
  key: string;
  kind: string;
  label: string;
  detail: string;
  params?: Record<string, unknown>[];
};

export function getMetricAtoms(): Promise<{ items: MetricAtom[] }> {
  return request<{ items: MetricAtom[] }>('/custom-metrics/atoms');
}

export type CustomMetricItem = {
  id: number;
  code: string;
  name: string;
  unit?: string;
  formula?: string;
  group_name?: string;
  inputs?: string;
  note?: string;
  steps?: unknown[];
};

export function listCustomMetrics(): Promise<{ items: CustomMetricItem[] }> {
  return request('/custom-metrics');
}

export function createCustomMetric(body: {
  code: string;
  name: string;
  unit?: string;
  formula?: string;
  group_name?: string;
  inputs?: string;
  note?: string;
  steps?: { atom: string; args?: Record<string, unknown> }[];
}): Promise<CustomMetricItem> {
  return request('/custom-metrics', { method: 'POST', body });
}

export function deleteCustomMetric(id: number): Promise<{ deleted: boolean }> {
  return request('/custom-metrics/' + id, { method: 'DELETE' });
}

export type EntityAccount = {
  key: string;
  bank_name: string;
  bank_code: string;
  account_masked: string;
  holders: Record<string, number>;
  tasks: number[];
};

export type EntitySubject = {
  subject: string;
  accounts?: string[];
  task_count?: number;
  [key: string]: unknown;
};

export type EntitiesPayload = {
  accounts: EntityAccount[];
  subjects: EntitySubject[];
  conflicts: { subject?: string; reason?: string; options?: unknown[] }[];
  summary: { accounts: number; subjects: number; multi_account_subjects: number; conflicts: number };
};

export function getEntities(): Promise<EntitiesPayload> {
  return request<EntitiesPayload>('/entities');
}

export type OcrRouting = {
  enabled: boolean;
  min_images: number;
  workers: number;
  model: string;
  endpoint: string;
  has_api_key: boolean;
  credential_ready: boolean;
};

export type QueueStats = {
  queued: number;
  running: number;
  failed: number;
  done: number;
  need_supplement: number;
  active_workers: number;
  max_workers: number;
  last_finished_at: number;
};

export type QueueJobItem = {
  task_id: number;
  biz_no: string;
  status: string;
  queue_position: number | null;
  carrier?: string | null;
  failure_code?: string | null;
  created_at?: string | null;
};

export function getQueueStats(): Promise<QueueStats> {
  return request<QueueStats>('/queue/stats');
}

export function listQueueJobs(includeFailed = true): Promise<{ items: QueueJobItem[]; total: number }> {
  return request(`/queue/jobs?include_failed=${includeFailed ? 'true' : 'false'}`);
}

export function retryQueueJob(taskId: number): Promise<{ task_id: number; status: string; mode: string }> {
  return request(`/queue/jobs/${taskId}/retry`, { method: 'POST' });
}

export function cancelQueueJob(taskId: number): Promise<{ task_id: number; status: string; cancelled: boolean }> {
  return request(`/queue/jobs/${taskId}/cancel`, { method: 'POST' });
}

export function getOcrRouting(): Promise<OcrRouting> {
  return request<OcrRouting>('/ocr-routing');
}

export function saveOcrRouting(patch: Partial<OcrRouting> & { api_key?: string }): Promise<OcrRouting> {
  return request<OcrRouting>('/ocr-routing', { method: 'PUT', body: patch });
}

export type AppUser = {
  id: number;
  username: string;
  role: string;
  display_name: string | null;
  is_admin: boolean;
  status: string;
  created_at: string | null;
  last_login_at: string | null;
};

export type MergeMethodInfo = {
  id: string;
  label: string;
  question?: string;
  approach?: string;
  impact?: string;
  when_to_use?: string;
  tier?: string;
  short: string;
  detail: string;
  formula: string;
  assumption: string;
  level: string;
};

export function getMergeMethods(): Promise<{
  methods: MergeMethodInfo[];
  overlap_modes: { id: string; label: string; detail: string }[];
}> {
  return request('/entities/methods');
}

export function getEntitiesMerge(subject: string, method = 'net_internal', overlap = 'max'): Promise<Record<string, unknown>> {
  const params = new URLSearchParams({ subject, method, overlap });
  return request('/entities/merge?' + params.toString());
}

export function mergeTasks(taskIds: number[], mode = 'net_internal'): Promise<Record<string, unknown>> {
  return request('/tasks/merge', { body: { task_ids: taskIds, mode } });
}

export function resolveEntityConflict(payload: { account_key: string; subject: string; note?: string }): Promise<{ ok: boolean }> {
  return request('/entities/conflicts/resolve', { body: payload });
}

export function undoEntityConflict(accountKey: string): Promise<{ ok: boolean }> {
  return request('/entities/conflicts/resolve?account_key=' + encodeURIComponent(accountKey), { method: 'DELETE' });
}

export function listUsers(): Promise<{ items: AppUser[] }> {
  return request<{ items: AppUser[] }>('/auth/users');
}

export function createUser(payload: {
  username: string;
  password: string;
  display_name?: string;
  is_admin?: boolean;
}): Promise<{ user: AppUser }> {
  return request('/auth/users', { body: { ...payload, role: 'banker' } });
}

export function updateUser(
  userId: number,
  payload: { display_name?: string; is_admin?: boolean; password?: string },
): Promise<{ user: AppUser }> {
  return request('/auth/users/' + userId, { method: 'PATCH', body: payload });
}

export function disableUser(userId: number): Promise<{ id: number; status: string }> {
  return request('/auth/users/' + userId, { method: 'DELETE' });
}

export function enableUser(userId: number): Promise<{ id: number; status: string }> {
  return request('/auth/users/' + userId + '/enable', { method: 'POST' });
}

export function changePassword(oldPassword: string, newPassword: string): Promise<{ changed: boolean }> {
  return request('/auth/change-password', { body: { old_password: oldPassword, new_password: newPassword } });
}
