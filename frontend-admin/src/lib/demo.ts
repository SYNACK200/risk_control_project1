import verifyJson from '../mocks/verify_result.json';
import metricsJson from '../mocks/metrics_report.json';
import ratesJson from '../mocks/interest_rates.json';

export interface LayerItem { code: string; name: string; result: string; detail?: string }
export interface Layer { verdict: string; reason?: string; items: LayerItem[] }
export interface Evidence { txn_id: number; rule_code: string; page_no: number; x: number; y: number; note: string }

export interface VerifyResult {
  note: string;
  task_id: string;
  carrier: string;
  verdict: string;
  verdict_reason: string;
  limitations: string[];
  layers: { carrier: Layer; content: Layer; ledger: Layer; external: Layer };
  evidence: Evidence[];
}

export interface MetricItem {
  code: string; name: string; value: string; unit: string; note: string; caliber_version: number;
}
export interface MetricGroup { key: string; name: string; metrics: MetricItem[] }
export interface Conclusion {
  code: string; label: string; level: string; threshold: string; value: string; hint: string;
}
export interface MetricsReport {
  note: string;
  task_id: string;
  carrier: string;
  metric_set_version: number;
  threshold_version: number;
  groups: MetricGroup[];
  conclusions: Conclusion[];
}

export interface RateRow { product: string; annual: string; min_balance: string }
export interface RateTable {
  note: string; basis_days: number; settlement_days: string; rates: RateRow[];
}

export const verifyDemo = verifyJson as unknown as VerifyResult;
export const metricsDemo = metricsJson as unknown as MetricsReport;
export const rateDemo = ratesJson as unknown as RateTable;
