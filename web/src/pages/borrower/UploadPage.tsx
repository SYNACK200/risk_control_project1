import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, getErrorMessage } from '../../api/errors';
import { composeTask, createTask, listMyTasks, type BorrowerTaskItem } from '../../api/borrower';
import { BANK_OPTIONS } from '../../lib/banks';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';

const MB = 1024 * 1024;
const CONCURRENCY = 2;

type Job = { id: number; name: string; size: number; status: 'waiting' | 'uploading' | 'done' | 'error'; taskId?: number; error?: string };

function formatSize(bytes: number) {
  return bytes >= MB ? (bytes / MB).toFixed(1) + ' MB' : Math.max(1, Math.round(bytes / 1024)) + ' KB';
}

function isPdf(file: File) {
  return file.type === 'application/pdf' || /\.pdf$/i.test(file.name);
}

function isImage(file: File) {
  return ['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || /\.(jpe?g|png|webp)$/i.test(file.name);
}

function monthStart(month: string) {
  return month ? month + '-01' : undefined;
}

function monthEnd(month: string) {
  if (!month) return undefined;
  const [year, number] = month.split('-').map(Number);
  const days = new Date(year, number, 0).getDate();
  return month + '-' + String(days).padStart(2, '0');
}

function currentMonth() {
  const now = new Date();
  return now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
}

export default function UploadPage() {
  const navigate = useNavigate();
  const [files, setFiles] = useState<File[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [recent, setRecent] = useState<BorrowerTaskItem[]>([]);
  const [error, setError] = useState('');
  const [warning, setWarning] = useState('');
  const [bankCode, setBankCode] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [password, setPassword] = useState('');
  const [needPassword, setNeedPassword] = useState(false);
  const [piplConsent, setPiplConsent] = useState(false);
  const [showPrivacyNote, setShowPrivacyNote] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listMyTasks(5)
      .then((res) => setRecent(res.items || []))
      .catch(() => {});
  }, []);

  async function inspect(list: File[]) {
    setError('');
    setWarning('');
    setJobs([]);
    const accepted: File[] = [];
    let lowQuality = 0;
    for (const file of list) {
      if (!isPdf(file) && !isImage(file)) {
        setError(file.name + '：仅支持 PDF、JPG、JPEG、PNG 文件。');
        return;
      }
      if (file.size === 0) {
        setError(file.name + '：文件为空，请重新选择。');
        return;
      }
      if (file.size > 20 * MB) {
        setError(file.name + '：单个文件不能超过 20MB。');
        return;
      }
      if (isImage(file)) {
        try {
          const bitmap = await createImageBitmap(file);
          const shortSide = Math.min(bitmap.width, bitmap.height);
          bitmap.close();
          if (shortSide < 480) lowQuality += 1;
        } catch {
          setError(file.name + '：图片无法读取，请重新导出或选择其他文件。');
          return;
        }
      }
      accepted.push(file);
    }
    accepted.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }));
    setFiles(accepted);
    if (lowQuality > 0) {
      setWarning('有 ' + lowQuality + ' 张图片清晰度偏低（短边 <480 像素），已允许提交，但可能影响识别。');
    }
  }

  function onPick(event: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (picked.length) void inspect(picked);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const dropped = Array.from(event.dataTransfer.files ?? []);
    if (dropped.length) void inspect(dropped);
  }

  function onPaste(event: React.ClipboardEvent) {
    const pasted = Array.from(event.clipboardData?.files ?? []);
    if (!pasted.length) return;
    event.preventDefault();
    void inspect(pasted);
  }

  const periodError =
    start && start > currentMonth()
      ? '开始月份不能晚于本月。'
      : end && end > currentMonth()
        ? '结束月份不能晚于本月。'
        : start && end && start > end
          ? '开始月份不能晚于结束月份。'
          : '';

  const canSubmit = Boolean(files.length && piplConsent && !submitting && !periodError && (!needPassword || password.trim()));

  async function submit() {
    if (!files.length) {
      setError('请先选择一份流水文件。');
      return;
    }
    if (!piplConsent) {
      setError('请先阅读并勾选个人金融信息处理单独同意条款。');
      return;
    }
    setSubmitting(true);
    setError('');
    const fields = {
      password: password || undefined,
      period_start: monthStart(start),
      period_end: monthEnd(end),
      bank_code: bankCode || undefined,
      consent_version: 'PIPL-v2026.1',
    };

    try {
      if (files.length > 1 && files.every(isImage)) {
        const created = await composeTask(fields, files);
        navigate('/app/tasks/' + created.task_id, { replace: true });
        return;
      }

      if (files.length === 1) {
        const created = await createTask(fields, files[0]);
        navigate('/app/tasks/' + created.task_id, { replace: true });
        return;
      }

      setJobs(files.map((file, index) => ({ id: index, name: file.name, size: file.size, status: 'waiting' })));
      let cursor = 0;
      const worker = async () => {
        while (true) {
          const index = cursor++;
          if (index >= files.length) return;
          setJobs((prev) => prev.map((job) => (job.id === index ? { ...job, status: 'uploading' } : job)));
          try {
            const created = await createTask(fields, files[index]);
            setJobs((prev) => prev.map((job) => (job.id === index ? { ...job, status: 'done', taskId: created.task_id } : job)));
          } catch (err) {
            if (err instanceof ApiError && err.code === 'E_ENCRYPT') {
              setNeedPassword(true);
              setError('部分文件设有打开口令，请填写口令后重新提交。');
            }
            const message = getErrorMessage(err, 'borrower');
            setJobs((prev) => prev.map((job) => (job.id === index ? { ...job, status: 'error', error: message } : job)));
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(CONCURRENCY, files.length) }, worker));
    } catch (err) {
      if (err instanceof ApiError && err.code === 'E_ENCRYPT') {
        setNeedPassword(true);
        setError('这份文件设置了打开口令，请输入口令后重试。');
      } else {
        setError(getErrorMessage(err, 'borrower'));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="panel" onPaste={onPaste}>
      <h1>上传个人银行流水</h1>
      <p className="sub">优先提交从手机银行/网银直接导出的原版 PDF；多张同一份流水的照片可多选合并提交。本页不展示风险评估结果。</p>

      {error ? <Notice>{error}</Notice> : null}
      {warning ? <Notice tone="info">{warning}</Notice> : null}

      {jobs.length > 0 ? (
        <table className="mini">
          <thead>
            <tr><th>#</th><th>文件</th><th>大小</th><th>状态</th><th>结果</th></tr>
          </thead>
          <tbody>
            {jobs.map((job, index) => (
              <tr key={job.id}>
                <td>{index + 1}</td>
                <td>{job.name}</td>
                <td className="muted small">{formatSize(job.size)}</td>
                <td>
                  {job.status === 'waiting' ? '排队中' : job.status === 'uploading' ? '上传中…' : job.status === 'done' ? '已受理' : '失败'}
                </td>
                <td>
                  {job.taskId ? (
                    <button className="link-btn" onClick={() => navigate('/app/tasks/' + job.taskId)}>
                      #{job.taskId} 查看进度
                    </button>
                  ) : job.error ? (
                    <span className="danger small">{job.error}</span>
                  ) : (
                    '—'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <div
        className={'drop' + (dragging ? ' dragging' : '') + (files.length ? ' has-file' : '')}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => input.current?.click()}
      >
        <input ref={input} type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp" hidden onChange={onPick} />
        {files.length ? (
          <div className="file-list">
            <p className="file-ok">✓ 已选择 {files.length} 个文件</p>
            <ol>
              {files.map((file, index) => (
                <li key={file.name + index}>
                  <span className="muted small">{index + 1}.</span>
                  <span>{file.name}</span>
                  <span className="muted small">{formatSize(file.size)}</span>
                  <button
                    type="button"
                    className="link-btn"
                    disabled={index === 0}
                    onClick={(event) => {
                      event.stopPropagation();
                      setFiles((prev) => {
                        if (index <= 0) return prev;
                        const next = [...prev];
                        [next[index - 1], next[index]] = [next[index], next[index - 1]];
                        return next;
                      });
                    }}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    className="link-btn"
                    disabled={index === files.length - 1}
                    onClick={(event) => {
                      event.stopPropagation();
                      setFiles((prev) => {
                        if (index >= prev.length - 1) return prev;
                        const next = [...prev];
                        [next[index], next[index + 1]] = [next[index + 1], next[index]];
                        return next;
                      });
                    }}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className="link-btn"
                    onClick={(event) => {
                      event.stopPropagation();
                      setFiles((prev) => prev.filter((_, i) => i !== index));
                    }}
                  >
                    移除
                  </button>
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <div>
            <p className="drop-title">点击选择，或把文件拖到这里</p>
            <p className="muted small">支持 PDF / JPG / PNG（单个 ≤ 20MB），支持多张图片自动合并、Ctrl+V 直接粘贴截图。</p>
          </div>
        )}
      </div>

      <div className="grid-3">
        <label className="field">
          <span>所属银行（可选，默认自动识别）</span>
          <select value={bankCode} onChange={(e) => setBankCode(e.target.value)}>
            <option value="">自动识别</option>
            {BANK_OPTIONS.map((b) => (
              <option key={b.code} value={b.code}>{b.label}</option>
            ))}
          </select>
        </label>
        <Field label="流水起始月（可选）" type="month" value={start} onChange={(event) => setStart(event.target.value)} />
        <Field label="流水结束月（可选）" type="month" value={end} onChange={(event) => setEnd(event.target.value)} />
      </div>
      {periodError ? <Notice>{periodError}</Notice> : null}

      <div className="consent-box">
        <label className="consent-check">
          <input type="checkbox" checked={piplConsent} onChange={(e) => setPiplConsent(e.target.checked)} />
          <span>
            我已阅读并<strong>单独同意</strong>授权银行处理本次提交的个人银行交易流水信息，用于信贷审核与真实性核验。
          </span>
        </label>
        <button type="button" className="link-btn" onClick={() => setShowPrivacyNote((v) => !v)}>
          {showPrivacyNote ? '收起声明全文' : '查看授权声明与保护说明'}
        </button>
        {showPrivacyNote && (
          <div className="consent-detail">
            根据《个人信息保护法》第二十九条关于处理敏感个人信息的规定：您所提交的银行流水账户信息与交易明细属于敏感个人信息，仅用于本次信贷风控审核与电子凭证核验，不会用于营销或向无关第三方提供；原始文件在平台内加密存储，仅经授权的审贷人员可查阅核验结论。
          </div>
        )}
      </div>

      <div style={{ marginTop: 8 }}>
        <label className="inline-toggle small muted">
          <input type="checkbox" checked={needPassword} onChange={(e) => setNeedPassword(e.target.checked)} />
          PDF 文件设有打开口令（提前填写以免二次上传）
        </label>
      </div>

      {needPassword ? (
        <Field
          label="文件打开口令"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          hint="口令只用于本次现场解密提取，不会落盘保存。"
        />
      ) : null}

      <div className="actions">
        <Button block disabled={!canSubmit} onClick={() => void submit()}>
          {submitting ? '提交中…' : '确认授权并提交给银行'}
        </Button>
      </div>

      {recent.length > 0 && (
        <div className="recent-box">
          <div className="recent-head">
            <span className="small muted">最近提交</span>
            <Link className="link-btn" to="/app/tasks">查看全部记录 ›</Link>
          </div>
          <ul className="plain small">
            {recent.map((r) => (
              <li key={r.id}>
                <Link to={'/app/tasks/' + r.id}>
                  <span className="mono">{r.biz_no}</span> · {r.status === 'DONE' ? '已完成' : r.status === 'NEED_SUPPLEMENT' ? '需补传' : r.status === 'FAILED' ? '未完成' : '处理中'}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
