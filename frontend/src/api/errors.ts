export type ApiErrorCode =
  | 'E_FORMAT'
  | 'E_BROKEN'
  | 'E_ENCRYPT'
  | 'E_NOLAYER'
  | 'E_MULTI'
  | 'E_CHECK'
  | 'E_STATE'
  | 'E_LIMIT'
  | 'E_IMAGE_LOWQ'
  | 'E_IMAGE_BLUR'
  | 'E_AUTH'
  | 'E_FORBID'
  | 'E_NOT_STATEMENT';

export type Audience = 'borrower' | 'admin';

const MESSAGES: Record<Audience, Record<ApiErrorCode, string>> = {
  borrower: {
    E_FORMAT: '文件格式不支持，请上传 PDF',
    E_BROKEN: '文件不完整，请重新下载',
    E_ENCRYPT: '文件已加密，请去掉口令',
    E_NOLAYER: '该文件像截图或扫描件',
    E_MULTI: '一次只能传一家银行',
    E_CHECK: '明细与合计对不上，请核对原件',
    E_STATE: '当前状态不能这样操作',
    E_LIMIT: '操作太频繁或文件过大',
    E_IMAGE_LOWQ: '图片太模糊，请重新拍摄或导出',
    E_IMAGE_BLUR: '关键信息看不清，请重新拍摄',
    E_AUTH: '登录已过期',
    E_FORBID: '没有权限查看',
    E_NOT_STATEMENT: '这不是银行流水文件，请上传对账单或交易明细',
  },
  admin: {
    E_FORMAT: '格式判定失败',
    E_BROKEN: '文件结构异常',
    E_ENCRYPT: '加密件',
    E_NOLAYER: '非官方导出件',
    E_MULTI: '来源不单一',
    E_CHECK: '数字核对失败，见定位行',
    E_STATE: '状态机拒绝',
    E_LIMIT: '触发限流',
    E_IMAGE_LOWQ: '短边不足 1000px',
    E_IMAGE_BLUR: '图片质量不达标',
    E_AUTH: '令牌无效',
    E_FORBID: '越权访问',
    E_NOT_STATEMENT: '预读判定非流水文件',
  },
};

export class ApiError extends Error {
  readonly code: string;
  readonly httpStatus?: number;
  readonly detail?: unknown;

  constructor(
    code: string,
    message: string,
    options: { httpStatus?: number; detail?: unknown } = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.httpStatus = options.httpStatus;
    this.detail = options.detail;
  }
}

function isKnownCode(code: string): code is ApiErrorCode {
  return code in MESSAGES.borrower;
}

export function getErrorMessage(error: unknown, audience: Audience): string {
  if (!(error instanceof ApiError)) return '操作失败，请稍后重试。';
  if (error.code === 'E_NETWORK') return '网络连接失败，请检查网络后重试。';
  if (error.code === 'E_UNKNOWN' || !isKnownCode(error.code)) return '操作失败，请稍后重试。';
  return MESSAGES[audience][error.code];
}
