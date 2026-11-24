import { request, requestBlob } from './client';

/** 特征 Lab 的接口在独立服务上（8020），由 dev 代理按路径前缀分流。 */

export type LabOperator = {
  key: string;
  family: string;
  kind: string;
  unit: string;
  detail: string;
  params: { name: string; type: string; default: unknown; detail: string }[];
};

export type LabFeature = {
  code: string;
  name: string;
  unit: string;
  form: string;
  body: unknown;
  version?: string;
  description?: string;
  category?: string;
};

export type LabSample = { name: string; group: string };

export type EvaluateResult = {
  value: string | number | boolean | null | (string | null)[];
  type: string;
  notes: string[];
  preview: (string | null)[] | null;
  rows: number;
};

export function listOperators(): Promise<{ items: LabOperator[] }> {
  return request<{ items: LabOperator[] }>('/lab/operators');
}

export function listFeatures(): Promise<{ items: LabFeature[] }> {
  return request<{ items: LabFeature[] }>('/lab/features');
}

export function listSamples(): Promise<{ items: LabSample[] }> {
  return request<{ items: LabSample[] }>('/lab/samples');
}

export function evaluate(sample: string, expr: string): Promise<EvaluateResult> {
  return request<EvaluateResult>('/lab/evaluate', { body: { sample, expr }, timeoutMs: 60000 });
}

export type InspectCell = { text: string; x0: number; x1: number; y0: number; y1: number };
export type InspectBand = {
  field: string;
  source: string;
  confidence: number;
  x0: number;
  x1: number;
  cells: InspectCell[];
};
export type InspectSingle = {
  field: string;
  label: string;
  page: number;
  value: string;
  x: number;
  y: number;
  w: number;
  h: number;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
};

export type InspectRegion = {
  area: { x: number; y: number; w: number; h: number };
  header_y: number | null;
  bands: InspectBand[];
};

export type InspectPage = {
  index: number;
  width: number;
  height: number;
  lines: number;
  header_y: number | null;
  header_index?: number;
  bands: InspectBand[];
  regions?: InspectRegion[];
  singles: InspectSingle[];
  has_text: boolean;
};
export type InspectReport = {
  pages: InspectPage[];
  page_count: number;
  text_layer: boolean;
  ocr_used?: boolean;
  ocr_pages?: number[];
};
export type SpreadBand = {
  page: number;
  width?: number;
  height?: number;
  keyword: InspectCell;
  anchor: InspectCell;
  x0: number;
  x1: number;
  cells: InspectCell[];
  source: string;
};
export type SpreadReport = { keyword: string; page_count: number; bands: SpreadBand[] };

export function inspectSample(sample: string, ocrPage = 0): Promise<InspectReport> {
  return request<InspectReport>(
    '/lab/inspect?sample=' + encodeURIComponent(sample) + '&ocr_page=' + ocrPage,
  );
}

export function spreadKeyword(sample: string, keyword: string, pageIndex?: number): Promise<SpreadReport> {
  return request<SpreadReport>(
    '/lab/spread?sample=' +
      encodeURIComponent(sample) +
      '&keyword=' +
      encodeURIComponent(keyword) +
      (pageIndex !== undefined ? '&page_index=' + pageIndex : ''),
  );
}

export function inspectFile(file: Blob, password?: string, ocrPage = 0, fileName = 'upload.pdf'): Promise<InspectReport> {
  const form = new FormData();
  form.append('file', file, fileName);
  form.append('ocr_page', String(ocrPage));
  if (password) form.append('password', password);
  return request<InspectReport>('/lab/inspect-file', { form, timeoutMs: 180000 });
}

export function spreadFile(
  file: Blob,
  keyword: string,
  password?: string,
  pageIndex?: number,
  fileName = 'upload.pdf',
): Promise<SpreadReport> {
  const form = new FormData();
  form.append('file', file, fileName);
  form.append('keyword', keyword);
  if (password) form.append('password', password);
  if (pageIndex !== undefined) form.append('page_index', String(pageIndex));
  return request<SpreadReport>('/lab/spread-file', { form, timeoutMs: 180000 });
}

export function sampleFileUrl(sample: string): string {
  return '/api/v1/lab/sample-file?sample=' + encodeURIComponent(sample);
}

export async function fetchSampleBytes(sample: string): Promise<ArrayBuffer> {
  const blob = await requestBlob('/lab/sample-file?sample=' + encodeURIComponent(sample));
  return blob.arrayBuffer();
}

export type CustomFeature = {
  code: string;
  name: string;
  expr: string;
  unit: string;
  version: number;
  description: string;
  created_at: string;
};

export function listCustom(): Promise<{ items: CustomFeature[] }> {
  return request<{ items: CustomFeature[] }>('/lab/custom');
}

export function saveCustom(payload: { code: string; name: string; expr: string; unit?: string; description?: string }): Promise<CustomFeature> {
  return request<CustomFeature>('/lab/custom', { body: payload });
}

export function deleteCustom(code: string): Promise<{ code: string; deleted: boolean }> {
  return request<{ code: string; deleted: boolean }>('/lab/custom/' + code, { method: 'DELETE' });
}

export function evaluateCode(sample: string, code: string): Promise<EvaluateResult> {
  return request<EvaluateResult>('/lab/evaluate', { body: { sample, code }, timeoutMs: 60000 });
}

export type ComputeFileFeatureRecord = {
  code: string;
  name: string;
  value: string | number | boolean | null;
  unit: string;
  reason: string;
  version: string;
};

export type ComputeFileResult = {
  file: string;
  rows: number;
  feature_count: number;
  features: ComputeFileFeatureRecord[];
};

export function computeFileFeatures(file: Blob, fileName = 'sample.pdf', codes?: string[]): Promise<ComputeFileResult> {
  const form = new FormData();
  form.append('file', file, fileName);
  if (codes && codes.length) form.append('codes', codes.join(','));
  return request<ComputeFileResult>('/features/compute-file', { form, timeoutMs: 180000 });
}
