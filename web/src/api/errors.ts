/**
 * 错误码 → 中文文案。三端唯一来源。
 *
 * 为什么保留两套文案：借款侧看到的是「你能怎么办」，银行侧看到的是「哪里判失败了」，
 * 同一错误码对两种人要说两种话。合并前端时最容易丢掉的就是这个区分。
 */
export type ApiErrorCode =
  | 'E_FORMAT' | 'E_BROKEN' | 'E_ENCRYPT' | 'E_NOLAYER' | 'E_MULTI' | 'E_CHECK'
  | 'E_STATE' | 'E_LIMIT' | 'E_IMAGE_LOWQ' | 'E_IMAGE_BLUR' | 'E_AUTH' | 'E_FORBID'
  | 'E_FORBIDDEN' | 'E_NOT_STATEMENT' | 'E_EXISTS' | 'E_NOT_FOUND' | 'E_SELF'
  | 'E_LAST_ADMIN' | 'E_PARAM' | 'E_NO_CREDENTIAL' | 'E_FEATURE' | 'E_EXPR' | 'E_OP';

export type Audience = 'borrower' | 'banker';

const MESSAGES: Record<Audience, Record<ApiErrorCode, string>> = {
  borrower: {
    E_FORMAT: '文件格式不支持，请上传 PDF',
    E_BROKEN: '文件不完整，请重新下载',
    E_ENCRYPT: '文件设有打开口令，请填写口令后提交',
    E_NOLAYER: '该文件像截图或扫描件',
    E_MULTI: '一次只能传一家银行',
    E_CHECK: '明细与合计对不上，请核对原件',
    E_STATE: '当前状态不能这样操作',
    E_LIMIT: '操作太频繁或文件过大',
    E_IMAGE_LOWQ: '图片太模糊，请重新拍摄或导出',
    E_IMAGE_BLUR: '关键信息看不清，请重新拍摄',
    E_AUTH: '登录已过期',
    E_FORBID: '没有权限查看',
    E_FORBIDDEN: '没有权限执行该操作',
    E_NOT_STATEMENT: '这不是银行流水文件，请上传对账单或交易明细',
    E_EXISTS: '记录已存在，请更换后重试',
    E_NOT_FOUND: '未找到对应记录',
    E_SELF: '不能对当前登录账号执行此操作',
    E_LAST_ADMIN: '至少需保留一位活跃管理员',
    E_PARAM: '提交的参数有误，请检查后重试',
    E_NO_CREDENTIAL: '未配置云端识别凭据',
    E_FEATURE: '特征定义有误',
    E_EXPR: '表达式语法有误',
    E_OP: '算子调用有误',
  },
  banker: {
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
    E_FORBIDDEN: '权限不足，仅管理员可操作',
    E_NOT_STATEMENT: '预读判定非流水文件',
    E_EXISTS: '记录已存在',
    E_NOT_FOUND: '目标对象不存在',
    E_SELF: '不能停用或修改当前自身权限',
    E_LAST_ADMIN: '系统至少需要保留一位活跃管理员',
    E_PARAM: '参数校验未通过',
    E_NO_CREDENTIAL: '未找到云端 OCR 凭据，无法开启',
    E_FEATURE: '特征定义校验失败',
    E_EXPR: '特征表达式语法错误',
    E_OP: '算子不存在或参数不合法',
  },
};

export class ApiError extends Error {
  readonly code: string;
  readonly httpStatus?: number;
  readonly detail?: unknown;

  constructor(code: string, message: string, options: { httpStatus?: number; detail?: unknown } = {}) {
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

const _GENERIC_HTTP_TEXT = /^(Bad Request|Unauthorized|Forbidden|Not Found|Conflict|Unprocessable Entity|Internal Server Error|Method Not Allowed)$/i;

function hasSpecificMessage(msg?: string): boolean {
  const m = (msg || '').trim();
  return Boolean(m && !_GENERIC_HTTP_TEXT.test(m));
}

const _PREFER_SERVER_MSG = new Set([
  'E_PARAM', 'E_STATE', 'E_EXISTS', 'E_NOT_FOUND', 'E_NO_CREDENTIAL',
  'E_FEATURE', 'E_EXPR', 'E_OP', 'E_SELF', 'E_LAST_ADMIN',
]);

export function getErrorMessage(error: unknown, audience: Audience): string {
  if (!(error instanceof ApiError)) return '操作失败，请稍后重试。';
  if (error.code === 'E_NETWORK') return '网络连接失败，请检查网络后重试。';
  // 登录密码错误（401 且后端给出明确中文提示）直接透出，不误报「登录已过期/令牌无效」
  if (error.code === 'E_AUTH' && hasSpecificMessage(error.message) && error.message !== '登录已过期') {
    return error.message;
  }
  if (error.code === 'E_UNKNOWN' || !isKnownCode(error.code)) {
    return hasSpecificMessage(error.message) ? error.message : '操作失败，请稍后重试。';
  }
  if (_PREFER_SERVER_MSG.has(error.code) && hasSpecificMessage(error.message)) {
    return error.message;
  }
  return MESSAGES[audience][error.code];
}
