export interface TaskRow { id: number; biz_no: string; status: string; carrier: string | null; created_at: string | null }
export interface ReportPayload {
  carrier: string; verdict: string; verdict_reason: string;
  limitations: string[]; layers: { layer: string; status: string; detail: string }[];
  metrics: { code: string; name: string; value: string | null; unit: string | null; note: string | null; caliber_version: number }[];
  metric_set_version: number; threshold_version: number;
  conclusions: { code: string; level: string; threshold: string; value: string }[];
  evidence: { txn_id: number | null; rule_code: string; page_no: number; x: number; y: number }[];
  materials: { file_id: number; role: string; pages: number | null; sha256: string | null }[];
  version: number;
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

export async function listTasks(): Promise<TaskRow[]> {
  return json<TaskRow[]>(await fetch(`${BASE}/tasks?limit=50`));
}

export async function getReport(taskId: number): Promise<ReportPayload> {
  return json<ReportPayload>(await fetch(`${BASE}/reports/${taskId}`));
}

export interface TxnRow {
  id: number; txn_date: string | null; direction: string | null;
  amount: string | null; balance: string | null; summary: string | null;
}

export async function getTransactions(taskId: number): Promise<TxnRow[]> {
  return json<TxnRow[]>(await fetch(`${BASE}/tasks/${taskId}/transactions?limit=2000`));
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
  valid?: boolean;
  field_map: Record<string, string | number>;
  provenance: InferRow[];
  columns: { index: number; x0: number; x1: number; samples: string[] }[];
  warnings: string[];
  template_id?: number;
}

export async function inferTemplate(form: FormData): Promise<InferResult> {
  return json<InferResult>(await fetch(BASE + '/templates/infer', { method: 'POST', body: form }));
}
