import { request } from './client';

/** 借款侧只有三个动作：提交、合并提交、查进度。 */

export type CreateTaskResult = {
  task_id: number;
  biz_no: string;
  status: string;
};

export type TaskDetail = {
  id: number;
  biz_no: string;
  status: string;
  carrier: string | null;
  period_start: string | null;
  period_end: string | null;
  failure_code: string | null;
  consent_version?: string | null;
  consent_at?: string | null;
  created_at: string | null;
};

function form(fields: Record<string, string | undefined>, files: File[], fieldName: string): FormData {
  const data = new FormData();
  files.forEach((file) => data.append(fieldName, file));
  Object.entries(fields).forEach(([key, value]) => {
    if (value) data.append(key, value);
  });
  return data;
}

export function createTask(fields: Record<string, string | undefined>, file: File): Promise<CreateTaskResult> {
  return request<CreateTaskResult>('/tasks', { form: form(fields, [file], 'file'), timeoutMs: 180000 });
}

export function composeTask(fields: Record<string, string | undefined>, files: File[]): Promise<CreateTaskResult> {
  return request<CreateTaskResult>('/tasks/compose', { form: form(fields, files, 'files'), timeoutMs: 300000 });
}

export function getTask(taskId: number): Promise<TaskDetail> {
  return request<TaskDetail>('/tasks/' + taskId);
}

export type BorrowerTaskItem = {
  id: number;
  biz_no: string;
  status: string;
  carrier: string | null;
  created_at: string | null;
  bank_name: string | null;
  period_start: string | null;
  period_end: string | null;
  consent_version?: string | null;
  consent_at?: string | null;
};

export function listMyTasks(limit = 50): Promise<{ items: BorrowerTaskItem[]; total: number }> {
  return request<{ items: BorrowerTaskItem[]; total: number }>('/tasks?limit=' + limit);
}

export function withdrawConsent(taskId: number): Promise<{ task_id: number; withdrawn: boolean; deleted_at: string }> {
  return request<{ task_id: number; withdrawn: boolean; deleted_at: string }>('/tasks/' + taskId + '/withdraw', {
    method: 'POST',
  });
}

export function supplementTask(taskId: number, file: File): Promise<{ task_id: number; status: string }> {
  const formData = new FormData();
  formData.append('file', file);
  return request<{ task_id: number; status: string }>('/tasks/' + taskId + '/supplement', {
    form: formData,
    timeoutMs: 180000,
  });
}
