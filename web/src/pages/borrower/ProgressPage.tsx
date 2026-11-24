import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getTask, supplementTask, type TaskDetail } from '../../api/borrower';
import { getErrorMessage } from '../../api/errors';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';

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

function failureText(code: string | null) {
  switch (code) {
    case 'E_FORMAT':
      return '文件格式无法识别，请从手机银行/网银重新导出原版 PDF 后上传。';
    case 'E_BROKEN':
      return '文件已损坏或不完整，请重新从银行客户端下载后上传。';
    case 'E_ENCRYPT':
      return '文件设有打开口令，请重新上传并填写正确的打开口令。';
    case 'E_NOT_STATEMENT':
      return '这份文件不是有效的银行交易流水，请确认后上传对账单或交易明细。';
    case 'E_NOLAYER':
      return '当前材料清晰度不足或缺少电子信息，请改传原版 PDF 或清晰完整的照片。';
    case 'E_MULTI':
      return '检测到同一文件混合了多家银行流水，请按银行分别导出后上传。';
    case 'E_CHECK':
      return '流水明细与页脚合计不一致，请核对原件后重新上传。';
    case 'E_IMAGE_LOWQ':
    case 'E_IMAGE_BLUR':
      return '照片分辨率过低或画面模糊，请在光线充足环境下重新拍摄或直接导出电子版 PDF。';
    default:
      return '处理未完成，请尝试重新上传原版材料或联系经办人员。';
  }
}

export default function ProgressPage() {
  const { id } = useParams();
  const taskId = Number(id);
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [error, setError] = useState('');
  const [supFile, setSupFile] = useState<File | null>(null);
  const [supBusy, setSupBusy] = useState(false);
  const [supNotice, setSupNotice] = useState('');
  const [notFound, setNotFound] = useState(false);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [pollSeed, setPollSeed] = useState(0);

  const fetchDetail = useCallback(() => getTask(taskId), [taskId]);

  useEffect(() => {
    if (!Number.isFinite(taskId)) return;
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
  }, [taskId, fetchDetail, pollSeed]);

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
      <div className="panel">
        <h1>未找到该提交记录</h1>
        <p className="sub">任务编号无效或无权查看，请返回提交记录列表确认。</p>
        <Link className="btn" to="/app/tasks">返回我的提交记录</Link>
      </div>
    );
  }
  const status = task?.status ?? 'PENDING';
  const current = stepIndex(status);
  const failed = status === 'FAILED';

  return (
    <div className="panel">
      <h1>处理进度</h1>
      <p className="sub">
        业务号 <span className="mono">{task?.biz_no ?? '—'}</span> · 提交时间{' '}
        {task?.created_at ? new Date(task.created_at).toLocaleString() : '—'}
        {task?.carrier ? ` · 材料类型：${task.carrier === 'electronic' ? '电子原件' : '影像/图片件'}` : ''}
        {elapsedSec > 0 && !['DONE', 'FAILED'].includes(status) ? ` · 已等待 ${elapsedSec} 秒` : ''}
      </p>

      {error ? <Notice>{error}</Notice> : null}
      {supNotice ? <Notice tone="ok">{supNotice}</Notice> : null}

      {failed ? (
        <Notice>{failureText(task?.failure_code ?? null)}</Notice>
      ) : (
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
          <div className="try-row" style={{ marginTop: 10 }}>
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

      <div className="actions">
        <Link className="btn" to="/app/upload">
          {failed ? '重新上传材料' : '再传一份'}
        </Link>
        <Link className="btn btn-ghost" to="/app/tasks">
          我的提交记录
        </Link>
      </div>

      <p className="muted small">本页只显示处理进度；审核结论与风险指标仅供银行工作人员查阅。</p>
    </div>
  );
}
