import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError, getErrorMessage } from '../api/errors';
import { getTask, type TaskDetail } from '../lib/api';

const POLL_MS = 3000;

const ACTIVE_STATUSES = new Set([
  'PENDING',
  'CHECKING',
  'PARSING',
  'VERIFYING',
  'REPORTING',
]);

const STATUS_COPY: Record<string, string> = {
  PENDING: '已收件，等待处理。',
  CHECKING: '正在检查材料。',
  PARSING: '正在解析流水。',
  NEED_SUPPLEMENT: '材料需要补充。',
  VERIFYING: '正在核验材料。',
  REPORTING: '正在生成处理结果。',
  DONE: '材料已提交，请等待银行处理。',
  FAILED: '处理未完成。',
};

const STAGES = ['已收件', '文件检查', '解析流水', '核验完成'];

const STAGE_INDEX: Record<string, number> = {
  PENDING: 0,
  CHECKING: 1,
  PARSING: 2,
  VERIFYING: 3,
  REPORTING: 3,
  DONE: 4,
};

const CARRIER_HINT: Partial<Record<string, string>> = {
  image: '材料为图片，处理时间可能较长。',
  screenshot: '材料为图片，处理时间可能较长；截图可能无法作为授信依据。',
};

const FAILURE_COPY: Record<string, { reason: string; next: string }> = {
  E_FORMAT: { reason: '文件格式不支持。', next: '请上传 PDF 文件。' },
  E_BROKEN: { reason: '文件不完整。', next: '请重新下载后再提交。' },
  E_ENCRYPT: { reason: '文件有打开口令。', next: '请回到上传页，输入口令后重新提交。' },
  E_NOLAYER: { reason: '材料像截图或扫描件。', next: '建议从手机银行导出电子 PDF 后提交。' },
  E_MULTI: { reason: '材料来自多家银行。', next: '请一次提交一家银行的流水。' },
  E_CHECK: { reason: '明细与合计对不上。', next: '请核对原件后重新提交。' },
  E_IMAGE_LOWQ: { reason: '图片清晰度不足。', next: '请重新拍摄或导出后提交。' },
  E_IMAGE_BLUR: { reason: '关键信息看不清。', next: '请重新拍摄或导出后提交。' },
};

const UNKNOWN_FAILURE = {
  reason: '材料未能完成处理。',
  next: '请稍后重试，或联系银行并提供业务号。',
};

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  if (total < 60) return `${total} 秒`;
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  if (minutes < 60) return `${minutes} 分 ${String(seconds).padStart(2, '0')} 秒`;
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
}

export function ProgressPage() {
  const { taskId } = useParams();
  const id = Number(taskId);
  const validId = Number.isFinite(id) && id > 0;
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(validId);
  const [error, setError] = useState('');
  const [notFound, setNotFound] = useState(!validId);
  const [pollingPaused, setPollingPaused] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!validId) return;
    let cancelled = false;
    let timeoutId: number | undefined;
    let hadData = task !== null;
    setLoading(task === null);

    async function tick() {
      try {
        const data = await getTask(id);
        if (cancelled) return;
        hadData = true;
        setTask(data);
        setLoading(false);
        setError('');
        setNotFound(false);
        setPollingPaused(false);
        if (ACTIVE_STATUSES.has(data.status)) {
          timeoutId = window.setTimeout(tick, POLL_MS);
        }
      } catch (cause) {
        if (cancelled) return;
        setLoading(false);
        if (hadData) {
          setPollingPaused(true);
          return;
        }
        if (cause instanceof ApiError && cause.httpStatus === 404) {
          setNotFound(true);
        } else {
          setError(getErrorMessage(cause, 'borrower'));
        }
      }
    }

    void tick();
    return () => {
      cancelled = true;
      if (timeoutId) window.clearTimeout(timeoutId);
    };
    // task 只用于判断是否已有数据，不参与轮询重启。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, validId, reloadKey]);

  useEffect(() => {
    if (!task?.created_at) return;
    const started = new Date(task.created_at).getTime();
    if (Number.isNaN(started)) return;
    const update = () => setElapsedMs(Date.now() - started);
    update();
    if (!ACTIVE_STATUSES.has(task.status)) return;
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [task?.created_at, task?.status]);

  const refresh = () => {
    setPollingPaused(false);
    setReloadKey(key => key + 1);
  };

  if (notFound) {
    return (
      <>
        <header className="top">
          <div className="wrap nav-wrap">
            <span className="brand">
              <span className="mark" aria-hidden="true">◈</span>
              银行流水材料提交
            </span>
          </div>
        </header>
        <main className="shell">
          <h1 className="page-title">没有找到该业务</h1>
          <p className="desc">链接可能已失效，或业务号不属于当前访问。</p>
          <Link className="btn" to="/">返回上传页</Link>
        </main>
      </>
    );
  }

  if (loading && !task) {
    return (
      <>
        <header className="top">
          <div className="wrap nav-wrap">
            <span className="brand">
              <span className="mark" aria-hidden="true">◈</span>
              银行流水材料提交
            </span>
          </div>
        </header>
        <main className="shell">
          <h1 className="page-title">材料受理进度</h1>
          <p className="desc">提交后由银行处理；本页只展示受理状态。</p>
          <section className="panel" aria-live="polite">
            <p className="muted">正在查询受理状态…</p>
          </section>
        </main>
      </>
    );
  }

  if (error && !task) {
    return (
      <>
        <header className="top">
          <div className="wrap nav-wrap">
            <span className="brand">
              <span className="mark" aria-hidden="true">◈</span>
              银行流水材料提交
            </span>
          </div>
        </header>
        <main className="shell">
          <h1 className="page-title">查询失败</h1>
          <p className="desc">没能获取到受理状态，可以重试一次。</p>
          <section className="panel">
            <p className="error" role="alert">{error}</p>
            <div className="actions">
              <button className="btn" type="button" onClick={refresh}>重试</button>
              <Link className="btn ghost" to="/">返回上传页</Link>
            </div>
          </section>
        </main>
      </>
    );
  }

  if (!task) {
    return (
      <>
        <header className="top">
          <div className="wrap nav-wrap">
            <span className="brand">
              <span className="mark" aria-hidden="true">◈</span>
              银行流水材料提交
            </span>
          </div>
        </header>
        <main className="shell">
          <h1 className="page-title">材料受理进度</h1>
          <section className="panel">
            <p className="muted">正在查询受理状态…</p>
          </section>
        </main>
      </>
    );
  }

  const active = ACTIVE_STATUSES.has(task.status);
  const failed = task.status === 'FAILED';
  const needSupplement = task.status === 'NEED_SUPPLEMENT';
  const stageIndex = STAGE_INDEX[task.status];
  const statusCopy = STATUS_COPY[task.status] ?? '状态更新中。';
  const failure = failed ? FAILURE_COPY[task.failure_code ?? ''] ?? UNKNOWN_FAILURE : null;
  const carrierHint = task.carrier ? CARRIER_HINT[task.carrier] : undefined;

  return (
    <>
      <header className="top">
        <div className="wrap nav-wrap">
          <span className="brand">
            <span className="mark" aria-hidden="true">◈</span>
            银行流水材料提交
          </span>
        </div>
      </header>

      <main className="shell">
        <h1 className="page-title">材料受理进度</h1>
        <p className="desc">提交后由银行处理；本页只展示受理状态，不展示结论。</p>

        <section className="panel progress-card">
          <p className="muted">业务号 {task.biz_no}</p>

          <div className="steps" aria-hidden="true">
            {STAGES.map((label, index) => {
              const reached = stageIndex !== undefined && index < stageIndex;
              const current = stageIndex !== undefined && index === stageIndex;
              return (
                <div key={label} className={`step${reached ? ' on' : ''}${current ? ' current' : ''}`}>
                  <div className="dot">{reached ? '✓' : index + 1}</div>
                  {label}
                </div>
              );
            })}
          </div>

          <div aria-live="polite">
            <h2 className={`status${failed ? ' red' : ''}`}>{statusCopy}</h2>
          </div>

          {active && (
            <p className="progress-meta">
              已用时 {formatElapsed(elapsedMs)}
              <span aria-hidden="true">·</span>
              每 3 秒自动刷新
            </p>
          )}
          {!active && task.created_at && (
            <p className="progress-meta">受理时间 {new Date(task.created_at).toLocaleString('zh-CN', { hour12: false })}</p>
          )}

          {carrierHint && <p className="tip">{carrierHint}</p>}

          {failure && (
            <div className="notice" role="alert">
              <b>{failure.reason}</b>
              <br />下一步：{failure.next}
              <br />如多次处理未成功，请联系银行并提供业务号 {task.biz_no}。
            </div>
          )}

          {needSupplement && (
            <div className="notice" role="status">
              <b>还缺材料。</b>
              <br />请补充缺少的月份或页码后重新提交；具体缺件明细可联系银行确认，并提供业务号 {task.biz_no}。
            </div>
          )}

          {pollingPaused && (
            <div className="notice" role="status">
              自动刷新暂时中断，当前状态可能不是最新。
              <button className="btn ghost" type="button" onClick={refresh}>手动刷新</button>
            </div>
          )}

          <div className="actions">
            <Link className="btn ghost" to="/">返回上传页</Link>
          </div>
        </section>
      </main>
    </>
  );
}
