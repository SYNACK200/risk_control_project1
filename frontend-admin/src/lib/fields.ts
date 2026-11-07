export interface FieldDef {
  code: string;
  label: string;
  type: 'string' | 'money' | 'date' | 'enum';
  scope: 'meta' | 'table' | 'both';
  required: boolean;
}

export const FIELD_DICT: FieldDef[] = [
  { code: 'account_no', label: '账号', type: 'string', scope: 'meta', required: true },
  { code: 'account_name', label: '户名', type: 'string', scope: 'meta', required: false },
  { code: 'bank_name', label: '开户行', type: 'string', scope: 'meta', required: false },
  // 这两个以前都叫「交易XX」，看起来像重复。其实一个是整份流水的起止日期（页眉一条），
  // 一个是每笔明细发生的日期（每行一条）。名字里把这件事说出来。
  { code: 'period', label: '流水起止日期', type: 'string', scope: 'meta', required: true },
  { code: 'currency', label: '币种', type: 'string', scope: 'meta', required: false },
  { code: 'opening_balance', label: '期初余额', type: 'money', scope: 'meta', required: false },
  { code: 'closing_balance', label: '期末余额', type: 'money', scope: 'meta', required: false },
  { code: 'total_in', label: '收入合计', type: 'money', scope: 'meta', required: false },
  { code: 'total_out', label: '支出合计', type: 'money', scope: 'meta', required: false },
  { code: 'branch', label: '开户网点', type: 'string', scope: 'meta', required: false },
  { code: 'txn_date', label: '每笔交易日期', type: 'date', scope: 'table', required: true },
  { code: 'summary', label: '摘要', type: 'string', scope: 'table', required: true },
  { code: 'counterparty', label: '对方户名', type: 'string', scope: 'table', required: false },
  { code: 'direction', label: '借贷方向', type: 'enum', scope: 'table', required: false },
  { code: 'amount', label: '发生额', type: 'money', scope: 'table', required: true },
  { code: 'balance', label: '余额', type: 'money', scope: 'table', required: true },
  { code: 'remark', label: '备注', type: 'string', scope: 'table', required: false },
];

export const REQUIRED_CODES: string[] = FIELD_DICT.filter(f => f.required).map(f => f.code);

export function labelOf(code: string, custom: { code: string; label: string }[]): string {
  const core = FIELD_DICT.find(f => f.code === code);
  if (core) return core.label;
  const own = custom.find(c => c.code === code);
  return own ? own.label : code;
}

export function fieldsForScope(
  scope: 'meta' | 'table',
  custom: { code: string; label: string }[],
): { code: string; label: string }[] {
  const core = FIELD_DICT
    .filter(f => f.scope === scope || f.scope === 'both')
    .map(f => ({ code: f.code, label: f.label }));
  return [...core, ...custom.map(c => ({ code: c.code, label: `${c.label}（自定义）` }))];
}

export const CODE_PATTERN = /^[a-z][a-z0-9_]{1,30}$/;