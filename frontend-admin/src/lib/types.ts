export interface Rect { x: number; y: number; w: number; h: number }

export interface MetaBox {
  id: string;
  field: string;
  page: number;
  rect: Rect;
}

export interface Column { field: string; x: number; w: number; fields?: string[] }

export interface TableSpec {
  id: string;
  page: number;
  area: Rect;
  headerY?: number;
  columns: Column[];
}

export interface CustomField { code: string; label: string }

export interface MatchRule {
  bank_name_keywords: string[];
  header_fingerprint: string[];
}

export interface FieldMapV1 {
  schema_version: 1;
  bank_code: string;
  page_size: { w: number; h: number };
  match_rule: MatchRule;
  meta_boxes: MetaBox[];
  tables: TableSpec[];
  custom_fields: CustomField[];
  meta: { created_at: string; sample_name?: string };
}

export type IssueLevel = 'error' | 'warning';

export interface Issue {
  code: string;
  level: IssueLevel;
  message: string;
  targetId?: string;
}

// select 是「不画任何东西，只选中/拖动」的模式。
// 之前没有它，默认是 meta（画字段框），导致表格区和列都点不中——
// 选不中就没有手柄，也就改不了大小。
export type Tool = 'select' | 'meta' | 'table' | 'column';

export type Selection =
  | { kind: 'meta'; id: string }
  | { kind: 'table'; id: string }
  | { kind: 'column'; tableId: string; index: number }
  | null;

export interface SamplePage {
  pageCount: number;
  width: number;
  height: number;
  render: (pageNo: number, target: HTMLCanvasElement, maxWidth: number) => Promise<void>;
  dispose: () => void;
}