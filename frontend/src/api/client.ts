import axios from 'axios';
import type { AxiosRequestConfig } from 'axios';
import { clearToken, getToken, notifyAuthRequired } from '../lib/auth';
import { ApiError } from './errors';

export interface ApiEnvelope<T> {
  code: number | string;
  message?: string;
  data: T;
}

const http = axios.create({
  baseURL: '/api/v1',
  timeout: 30_000,
});

http.interceptors.request.use(config => {
  const token = getToken();
  if (token) config.headers.set('Authorization', `Bearer ${token}`);
  return config;
});

function isEnvelope(body: unknown): body is ApiEnvelope<unknown> {
  return typeof body === 'object' && body !== null && 'code' in body && 'data' in body;
}

function parseErrorBody(body: unknown): { code?: string; message?: string } {
  if (!body || typeof body !== 'object') return {};
  const record = body as Record<string, unknown>;
  const detail = record.detail;
  if (detail && typeof detail === 'object') {
    const nested = detail as Record<string, unknown>;
    return {
      code: typeof nested.code === 'string' ? nested.code : undefined,
      message: typeof nested.message === 'string' ? nested.message : undefined,
    };
  }
  if (typeof detail === 'string') return { message: detail };
  return {
    code: typeof record.code === 'string' ? record.code : undefined,
    message: typeof record.message === 'string' ? record.message : undefined,
  };
}

http.interceptors.response.use(
  response => {
    const body = response.data;
    if (isEnvelope(body)) {
      if (body.code === 'E_AUTH') { clearToken(); notifyAuthRequired(); }
      if (body.code !== 0) {
        throw new ApiError(String(body.code), body.message ?? '请求失败', {
          httpStatus: response.status,
          detail: body,
        });
      }
    }
    return response;
  },
  error => {
    if (error instanceof ApiError) return Promise.reject(error);
    if (!axios.isAxiosError(error)) {
      return Promise.reject(new ApiError('E_UNKNOWN', '请求失败', { detail: error }));
    }
    if (!error.response) {
      return Promise.reject(new ApiError('E_NETWORK', '网络不可用', { detail: error }));
    }

    const { code, message } = parseErrorBody(error.response.data);
    if (code === 'E_AUTH' || error.response.status === 401 || error.response.status === 503) {
      clearToken();
      notifyAuthRequired();
    }
    return Promise.reject(
      new ApiError(code ?? 'E_UNKNOWN', message ?? error.message, {
        httpStatus: error.response.status,
        detail: error.response.data,
      }),
    );
  },
);

export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await http.request<unknown>(config);
  const body = response.data;
  if (isEnvelope(body)) return body.data as T;
  return body as T;
}
