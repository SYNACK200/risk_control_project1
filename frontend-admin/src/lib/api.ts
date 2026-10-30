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

async function json<T>(res: Response): Promise<T> {
  const data = await res.json().catch(() => null);
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
  materials: number; limitations: number; report_version: number | null;
}

export interface TaskFacets {
  authenticity: Record<string, number>;
  risk: Record<string, number>;
  parse: Record<string, number>;
  bank: Record<string, number>;
  total: number;
}

export interface TaskSummaryList { items: TaskSummary[]; total: number; facets: TaskFacets }

export interface TaskFilters {
  authenticity?: string;
  risk?: string;
  parse?: string;
  bank?: string;
  date_from?: string;
  date_to?: string;
  q?: string;
  limit?: number;
}

export async function listTasks(filters: TaskFilters = {}): Promise<TaskSummaryList> {
  const params = new URLSearchParams();
  params.set('limit', String(filters.limit ?? 500));
  for (const key of ['authenticity', 'risk', 'parse', 'bank', 'date_from', 'date_to', 'q'] as const) {
    const value = filters[key];
    if (value) params.set(key, value);
  }
  return json<TaskSummaryList>(await fetch(BASE + '/tasks?' + params.toString()));
}

export async function reanalyzeTask(taskId: number, password?: string): Promise<{ task_id: number; version: number }> {
  const form = new FormData();
  if (password) form.append('password', password);
  return json<{ task_id: number; version: number }>(await fetch(BASE + '/tasks/' + taskId + '/reanalyze', {
    method: 'POST', body: form,
  }));
}

export async function getReport(taskId: number): Promise<ReportPayload> {
  return json<ReportPayload>(await fetch(`${BASE}/reports/${taskId}`));
}

export interface TxnRow {
  id: number; txn_date: string | null; direction: string | null;
  amount: string | null; balance: string | null; summary: string | null;
  counterparty_name?: string | null; page_no?: number | null; confidence?: string | null;
}

export async function getTransactions(taskId: number): Promise<TxnRow[]> {
  return json<TxnRow[]>(await fetch(`${BASE}/tasks/${taskId}/transactions?limit=2000`));
}

export interface ReportCheck { code: string; name: string; status: string; detail: string }

export interface VerificationDef { code: string; layer: string; method: string }

export async function getVerificationDefinitions(): Promise<{ items: VerificationDef[] }> {
  return json<{ items: VerificationDef[] }>(await fetch(BASE + '/verification-definitions'));
}

export interface MetricDef {
  code: string; name: string; unit: string; group: string;
  formula: string; inputs: string; viz: string;
}

export interface MetricDefs { metric_set_version: number; items: MetricDef[] }

export async function getMetricDefinitions(): Promise<MetricDefs> {
  return json<MetricDefs>(await fetch(BASE + '/metric-definitions'));
}

export async function getTask(taskId: number): Promise<TaskRow> {
  return json<TaskRow>(await fetch(`${BASE}/tasks/${taskId}`));
}

export interface TemplateRow { id: number; bank_code: string; version: number; status: string; field_map: Record<string, unknown> }

export async function listTemplates(): Promise<TemplateRow[]> {
  return json<TemplateRow[]>(await fetch(`${BASE}/templates`));
}

export async function createTemplate(body: { bank_code: string; field_map: Record<string, unknown>; header_columns?: string[]; version?: number }): Promise<{ id: number }> {
  return json<{ id: number }>(await fetch(`${BASE}/templates`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }));
}

export async function publishTemplate(id: number): Promise<{ status: string }> {
  return json<{ status: string }>(await fetch(`${BASE}/templates/${id}/publish`, { method: 'POST' }));
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
  return json<InferResult>(await fetch(BASE + '/templates/infer', { method: 'POST', body: form }));
}
