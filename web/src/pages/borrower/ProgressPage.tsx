import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getTask, listMyTasks, supplementTask, type TaskDetail } from '../../api/borrower';
import { getFailureGuide, getErrorMessage } from '../../api/errors';
import { Button } from '../../ui/Button';
import { EmptyState } from '../../ui/EmptyState';
import { Notice } from '../../ui/Notice';
import { PageHeader } from '../../ui/PageHeader';

const STEPS: { key: string; label: string }[] = [
  { key: 'QUEUED', label: '已受理，等待开始' },
  { key: 'CHECKING', label: '检查文件完整性' },
  { key: 'PARSING', label: '识别流水明细' },
  { key: 'VERIFYING', label: '核验材料真实性' },
  { key: 'REPORTING', label: '生成审核资料' },
  { key: 'DONE', label: '处理完成' },
];

const ORDER = STEPS.map((step) => step.key);

function stepIndex(status: string) {
  const index = ORDER.indexOf(status);
  if (status === 'PENDING') return -1;
  if (status === 'NEED_SUPPLEMENT') return ORDER.indexOf('PARSING');
  return index;
}

/**
 * 单个任务的进度。没带任务号时默认看最近一条提交（列表按提交时间倒序）。
 * 本页只显示处理进度；审核结论与风险指标仅供银行工作人员查阅。
 */
export default function ProgressPage({ active = true }: { active?: boolean } = {}) {
  const { id } = useParams();
  const [latest, setLatest] = useState<{ id: number | null; error: string } | null>(null);

  useEffect(() => {
    if (id) return;
    let alive = true;
    listMyTasks(1)
      .then((res) => {
        if (alive) setLatest({ id: res.items?.[0]?.id ?? null, error: '' });
      })
      .catch((err) => {
        if (alive) setLatest({ id: null, error: getErrorMessage(err, 'borrower') });
      });
    return () => {
      alive = false;
    };
  }, [id]);

  if (id) return <TaskProgress key={id} taskId={Number(id)} active={active} />;
  if (!latest) return <p className="muted">加载中…</p>;
  if (latest.error) {
    return (
      <>
        <Notice>{latest.error}</Notice>
        <Link className="btn btn-ghost" to="/app/progress?tab=history">查看我的提交记录</Link>
      </>
    );
  }
  if (latest.id === null) {
    return (
      <EmptyState
        title="还没有提交记录"
        hint="上传一份银行流水后，可以在这里看到它走到哪一步。"
        action={
          <Link className="btn" to="/app">
            去上传流水
          </Link>
        }
      />
    );
  }
  return <TaskProgress key={latest.id} taskId={latest.id} active={active} />;
}

function TaskProgress({ taskId, active }: { taskId: number; active: boolean }) {
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [error, setError] = useState('');
  const [supFile, setSupFile] = useState<File | null>(null);
  const [supBusy, setSupBusy] = useState(false);
  const [supNotice, setSupNotice] = useState('');
  const [notFound, setNotFound] = useState(false);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [pollSeed, setPollSeed] = useState(0);

  const fetchDetail = useCallback(() => getTask(taskId), [taskId]);

  // 不在「当前」页签时不轮询，切回来再续上
  useEffect(() => {
    if (!Number.isFinite(taskId) || !active) return;
    let alive = true;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const detail = await fetchDetail();
        if (!alive) return;
        setTask(detail);
        setError('');
        setNotFound(false);
        if (detail.status !== 'DONE' && detail.status !== 'FAILED' && detail.status !== 'NEED_SUPPLEMENT') {
          timer = window.setTimeout(tick, 2000);
        }
      } catch (err) {
        if (!alive) return;
        const statusNum = (err as { httpStatus?: number })?.httpStatus;
        if (statusNum === 404) {
          setNotFound(true);
          return;
        }
        setError(getErrorMessage(err, 'borrower'));
        timer = window.setTimeout(tick, 4000);
      }
    };

    void tick();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [taskId, fetchDetail, pollSeed, active]);

  useEffect(() => {
    if (!task || ['DONE', 'FAILED', 'NEED_SUPPLEMENT'].includes(task.status)) return;
    const idTimer = window.setInterval(() => setElapsedSec((s) => s + 1), 1000);
    return () => window.clearInterval(idTimer);
  }, [task]);

  const handleSupplement = async () => {
    if (!supFile) return;
    setSupBusy(true);
    setError('');
    setSupNotice('');
    try {
      await supplementTask(taskId, supFile);
      setSupFile(null);
      setSupNotice('补充材料已上传，系统正在重新处理。');
      const updated = await fetchDetail();
      setTask(updated);
      setPollSeed((n) => n + 1);
    } catch (err) {
      setError(getErrorMessage(err, 'borrower'));
    } finally {
      setSupBusy(false);
    }
  };

  if (notFound) {
    return (
      <>
        <PageHeader description="任务编号无效或无权查看，请到「历史」页签确认。" />
        <Link className="btn" to="/app/progress?tab=history">查看我的提交记录</Link>
      </>
    );
  }
  const status = task?.status ?? 'PENDING';
  const current = stepIndex(status);
  const failed = status === 'FAILED';

  return (
    <>
      <PageHeader
        description={
          <>
            任务 #{taskId}{task?.biz_no ? `（${task.biz_no}）` : ''} · 提交时间 {task?.created_at ? new Date(task.created_at).toLocaleString() : '—'}
            {task?.carrier ? ` · 材料类型：${task.carrier === 'electronic' ? '电子原件' : '影像/图片件'}` : ''}
            {elapsedSec > 0 && !['DONE', 'FAILED'].includes(status) ? ` · 已等待 ${elapsedSec} 秒` : ''}
          </>
        }
        actions={
          <Link className="btn" to="/app">
            {failed ? '重新上传材料' : '再传一份'}
          </Link>
        }
      />

      {error ? <Notice>{error}</Notice> : null}
      {supNotice ? <Notice tone="ok">{supNotice}</Notice> : null}

      {failed ? <Notice>{getFailureGuide(task?.failure_code)}</Notice> : (
        <ol className="timeline">
          {STEPS.map((step, index) => {
            const state = index < current ? 'done' : index === current ? 'active' : 'todo';
            return (
              <li key={step.key} className={'timeline-item ' + state}>
                <span className="dot" />
                <span>{step.label}</span>
              </li>
            );
          })}
        </ol>
      )}

      {status === 'NEED_SUPPLEMENT' ? (
        <div className="supplement-box">
          <Notice tone="info">当前材料部分页次不清晰或信息不完整，请补充清晰的原版 PDF 或照片。</Notice>
          <div className="try-row">
            <input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.webp"
              onChange={(e) => setSupFile(e.target.files?.[0] ?? null)}
            />
            <Button size="sm" disabled={!supFile || supBusy} onClick={() => void handleSupplement()}>
              {supBusy ? '上传中…' : '上传补充材料'}
            </Button>
          </div>
        </div>
      ) : null}

      <p className="muted small">本页只显示处理进度；审核结论与风险指标仅供银行工作人员查阅。</p>
    </>
  );
}
