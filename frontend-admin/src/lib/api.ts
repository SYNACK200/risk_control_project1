import { getToken, notifyAuthRequired } from './auth';

export interface PrereadInfo {
  verdict: string; is_statement: boolean; confidence: number;
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
export interface ReportPayload {
  carrier: string; verdict: string; verdict_reason: string;
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
  authenticity: { level: string; label: string; blocked_layers: string[]; limited_layers: string[] };
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

export interface TaskSummaryList { items: TaskSummary[]; total: number; facets: TaskFacets }

export interface TaskFilters {
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
  params.set('limit', String(filters.limit ?? 500));
  for (const key of ['authenticity', 'source', 'risk', 'risk_code', 'parse', 'bank', 'date_from', 'date_to', 'q'] as const) {
    const value = filters[key];
    if (value) params.set(key, value);
  }
  if (filters.min_income !== undefined) params.set('min_income', String(filters.min_income));
  if (filters.max_income !== undefined) params.set('max_income', String(filters.max_income));
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

export async function getMergeModes(): Promise<{ items: FlowMergeMode[] }> {
  return json<{ items: FlowMergeMode[] }>(await authFetch(BASE + '/tasks/merge/modes'));
}

export async function mergeTasks(taskIds: number[], mode: string): Promise<FlowMergeResult> {
  return json<FlowMergeResult>(await authFetch(BASE + '/tasks/merge', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_ids: taskIds, mode }),
  }));
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

export async function createTemplate(body: { bank_code: string; field_map: Record<string, unknown>; header_columns?: string[]; version?: number }): Promise<{ id: number }> {
  return json<{ id: number }>(await authFetch(`${BASE}/templates`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }));
}

export async function publishTemplate(id: number): Promise<{ status: string }> {
  return json<{ status: string }>(await authFetch(`${BASE}/templates/${id}/publish`, { method: 'POST' }));
}



export interface InferRow { field: string; column: number | null; source: string; confidence: number; why: string }
export interface InferResult {
  bank_code: string;
  field_map: Record<string, string | number>;
  provenance: InferRow[];
  columns: { index: number; x0: number; x1: number; samples: string[] }[];
  warnings: string[];
  template_id?: number;
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
  unsupported: { code: string; name: string; reason: string }[];
  warnings: string[];
  explain: { why_this_method: string; assumption: string; ratio_rule: string; balance_rule: string };
}

export interface EntitiesPayload {
  accounts: EntityAccount[]; subjects: EntitySubject[]; conflicts: EntityConflict[];
  summary: { accounts: number; subjects: number; multi_account_subjects: number; conflicts: number };
}

export interface SubjectMergeMethod {
  id: string; label: string; short: string; detail: string; formula: string; assumption: string;
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
  history: { version: number; note: string | null; created_at: string | null; values: Record<string, string | number | null> }[];
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
