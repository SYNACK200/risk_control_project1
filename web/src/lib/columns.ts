/** 列的中文名：界面上不出现 txn_date 这种代号，使用者是银行员工不是程序员。 */
export const COLUMN_LABELS: { key: string; label: string; hint?: string }[] = [
  { key: 'txn_date', label: '交易日期', hint: '如 2026-01-05' },
  { key: 'trade_time', label: '交易时间', hint: '如 14:32:10' },
  { key: 'summary', label: '摘要', hint: '如 工资、消费、转账' },
  { key: 'counterparty_name', label: '对方户名', hint: '如 某某公司' },
  { key: 'amount', label: '交易金额', hint: '一列里带正负或借贷标志' },
  { key: 'amount_in', label: '收入金额', hint: '只装进账金额的那一列' },
  { key: 'amount_out', label: '支出金额', hint: '只装出账金额的那一列' },
  { key: 'balance', label: '余额', hint: '如 13,200.00' },
  { key: 'direction', label: '借贷标志', hint: '如 借 / 贷' },
  { key: 'account_no', label: '卡号或账号' },
  { key: 'reference_no', label: '流水号' },
];

/** 系统内部可能给出别的叫法（counterparty / date / time），界面上统一翻成中文。 */
const ALIASES: Record<string, string> = {
  counterparty: 'counterparty_name',
  date: 'txn_date',
  time: 'trade_time',
  amount_in_total: 'amount_in',
  amount_out_total: 'amount_out',
};

/** 把解析侧使用的字段名归一化到界面上的规范名（模板里可能存 counterparty/date/time）。 */
export function canonicalField(key: string): string {
  return ALIASES[key] ?? key;
}

export function labelOf(key: string): string {
  const canonical = ALIASES[key] ?? key;
  return COLUMN_LABELS.find((item) => item.key === canonical)?.label ?? key;
}
