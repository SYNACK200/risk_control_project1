import { request } from '../api/client';

export interface CreateTaskResult {
  task_id: number;
  biz_no: string;
  status: string;
  carrier: string;
  txn_count: number;
}

export function createTask(form: FormData): Promise<CreateTaskResult> {
  return request<CreateTaskResult>({
    method: 'POST',
    url: '/tasks',
    data: form,
    timeout: 180_000,
  });
}

export type Carrier = 'electronic' | 'image' | 'screenshot';

export interface TaskDetail {
  id: number;
  biz_no: string;
  status: string;
  carrier: Carrier | null;
  period_start: string | null;
  period_end: string | null;
  failure_code: string | null;
  created_at: string | null;
}

export function getTask(taskId: number): Promise<TaskDetail> {
  return request<TaskDetail>({ method: 'GET', url: `/tasks/${taskId}` });
}
