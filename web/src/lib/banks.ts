/** 公共银行选项列表：供借款侧与银行侧共享，避免借款侧分包反向依赖银行侧标注模块。 */
export const BANK_OPTIONS: { code: string; label: string }[] = [
  { code: 'ICBC', label: '工商银行' },
  { code: 'CCB', label: '建设银行' },
  { code: 'ABC', label: '农业银行' },
  { code: 'BOC', label: '中国银行' },
  { code: 'BCM', label: '交通银行' },
  { code: 'PSBC', label: '邮储银行' },
  { code: 'CMB', label: '招商银行' },
  { code: 'CGB', label: '广发银行' },
  { code: 'SPDB', label: '浦发银行' },
  { code: 'PAB', label: '平安银行' },
  { code: 'CEB', label: '光大银行' },
  { code: 'CITIC', label: '中信银行' },
  { code: 'CIB', label: '兴业银行' },
  { code: 'CMBC', label: '民生银行' },
  { code: 'WECHAT', label: '微信账单' },
  { code: 'ALIPAY', label: '支付宝账单' },
];
