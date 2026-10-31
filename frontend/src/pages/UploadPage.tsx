import { useRef, useState } from 'react';
import type { ChangeEvent, DragEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError, getErrorMessage } from '../api/errors';
import { composeTask, createTask } from '../lib/api';

const MB = 1024 * 1024;

function toMonthStart(month: string) {
  return `${month}-01`;
}

function toMonthEnd(month: string) {
  const [year, monthNumber] = month.split('-').map(Number);
  const days = new Date(year, monthNumber, 0).getDate();
  return `${month}-${String(days).padStart(2, '0')}`;
}

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

function formatSize(bytes: number) {
  return bytes >= MB ? `${(bytes / MB).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [multiTasks, setMultiTasks] = useState<number[]>([]);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [agreed, setAgreed] = useState(false);
  const [password, setPassword] = useState('');
  const [needPassword, setNeedPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [checkingName, setCheckingName] = useState('');
  const selection = useRef(0);
  const navigate = useNavigate();

  async function checkOne(candidate: File): Promise<string | null> {
    const isPdf = candidate.type === 'application/pdf' && /\.pdf$/i.test(candidate.name);
    const isImage = ['image/jpeg', 'image/png'].includes(candidate.type) && /\.(jpe?g|png)$/i.test(candidate.name);
    if (!isPdf && !isImage) return '仅支持 PDF、JPG、JPEG、PNG 文件。';
    if (candidate.size === 0) return '文件为空，请重新选择。';
    if (candidate.size > (isPdf ? 20 : 10) * MB) return isPdf ? 'PDF 不能超过 20MB。' : '图片不能超过 10MB。';
    if (isImage) {
      let image: ImageBitmap;
      try { image = await createImageBitmap(candidate); } catch { return '图片无法读取，请重新导出或选择其他文件。'; }
      const shortSide = Math.min(image.width, image.height);
      image.close();
      if (shortSide < 1000) return '图片短边不足 1000 像素，请重新拍摄或导出。';
    }
    return null;
  }

  async function selectFiles(list: FileList | File[] | null) {
    const arr = Array.from(list ?? []);
    if (!arr.length) return;
    setError(''); setMultiTasks([]); setNeedPassword(false); setPassword('');
    for (const f of arr) {
      const problem = await checkOne(f);
      if (problem) { setError(f.name + '：' + problem); setFiles([]); setFile(null); return; }
    }
    setFiles(arr);
    setFile(arr[0] ?? null);
  }

  async function selectFile(candidate?: File) {
    const current = ++selection.current;
    setFile(null); setError(''); setChecking(false); setNeedPassword(false); setPassword('');
    setCheckingName(candidate?.name ?? '');
    if (!candidate) return;
    setChecking(true);
    try {
      const isPdf = candidate.type === 'application/pdf' && /\.pdf$/i.test(candidate.name);
      const isImage = ['image/jpeg', 'image/png'].includes(candidate.type) && /\.(jpe?g|png)$/i.test(candidate.name);
      if (!isPdf && !isImage) throw new Error('仅支持 PDF、JPG、JPEG、PNG 文件。');
      if (candidate.size === 0) throw new Error('文件为空，请重新选择。');
      if (candidate.size > (isPdf ? 20 : 10) * MB) throw new Error(isPdf ? 'PDF 不能超过 20MB。' : '图片不能超过 10MB。');
      if (isImage) {
        let image: ImageBitmap;
        try { image = await createImageBitmap(candidate); } catch { throw new Error('图片无法读取，请重新导出或选择其他文件。'); }
        const shortSide = Math.min(image.width, image.height);
        image.close();
        if (shortSide < 1000) throw new Error('图片短边不足 1000 像素，请重新拍摄或导出。');
      }
      if (selection.current === current) setFile(candidate);
    } catch (cause) {
      if (selection.current === current) setError(cause instanceof Error ? cause.message : '文件检查失败，请重试。');
    } finally {
      if (selection.current === current) { setChecking(false); setCheckingName(''); }
    }
  }

  function dropFile(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    void selectFiles(event.dataTransfer.files);
  }

  function changeFile(event: ChangeEvent<HTMLInputElement>) {
    void selectFiles(event.target.files);
    event.target.value = '';
  }

  async function submit() {
    if (files.length > 1) {
      setSubmitting(true); setError(''); setMultiTasks([]);
      try {
        const allImages = files.every(f => !/\.pdf$/i.test(f.name));
        if (allImages) {
          // 同一份流水的多张照片：按顺序合成一份材料
          const form = new FormData();
          files.forEach(f => form.append('files', f));
          if (password) form.append('password', password);
          if (start) form.append('period_start', toMonthStart(start));
          if (end) form.append('period_end', toMonthEnd(end));
          const created = await composeTask(form);
          navigate('/tasks/' + created.task_id, { replace: true });
          return;
        }
        // 多份流水：每份单独受理
        const ids: number[] = [];
        for (const f of files) {
          const form = new FormData();
          form.append('file', f);
          if (password) form.append('password', password);
          if (start) form.append('period_start', toMonthStart(start));
          if (end) form.append('period_end', toMonthEnd(end));
          const created = await createTask(form);
          ids.push(created.task_id);
        }
        setMultiTasks(ids);
      } catch (err) {
        if (err instanceof ApiError && err.code === 'E_ENCRYPT') {
          setNeedPassword(true);
          setError('有文件设置了打开口令，请输入口令后重试。');
        } else {
          setError(getErrorMessage(err, 'borrower'));
        }
      } finally {
        setSubmitting(false);
      }
      return;
    }
    if (!file) { setError('请先选择一份流水文件。'); return; }
    setSubmitting(true); setError('');
    try {
      const form = new FormData();
      form.append('file', file);
      if (password) form.append('password', password);
      if (start) form.append('period_start', toMonthStart(start));
      if (end) form.append('period_end', toMonthEnd(end));
      const created = await createTask(form);
      navigate(`/tasks/${created.task_id}`, { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'E_ENCRYPT') {
        setNeedPassword(true);
        setError('该文件有打开口令，请输入口令后重试。');
      } else if (err instanceof ApiError && err.code === 'E_NOT_STATEMENT') {
        setError(err.message || getErrorMessage(err, 'borrower'));
      } else {
        setError(getErrorMessage(err, 'borrower'));
      }
    } finally {
      setSubmitting(false);
    }
  }

  const thisMonth = currentMonth();
  const periodError = start && start > thisMonth
    ? '开始月份不能晚于本月。'
    : end && end > thisMonth
      ? '结束月份不能晚于本月。'
      : start && end && start > end
        ? '开始月份不能晚于结束月份。'
        : '';
  // 业务口径：唯一必填是流水文件；授权确认只提示不阻断（合规口径由 PM/PD 定）
  const canSubmit = Boolean((files.length > 1 || file) && !submitting && !periodError && (!needPassword || password.trim()));

  return (
    <>
      <header className="top"><div className="wrap nav-wrap"><span className="brand"><span className="mark" aria-hidden="true">◈</span>银行流水材料提交</span></div></header>
      <main className="shell">
        <h1 className="page-title">上传个人银行流水</h1>
        <p className="desc">只需提交流水文件，其他信息都可以不填。</p>
        <aside className="notice" role="note">提交后由银行处理；本页不展示任何结论或指标。</aside>

        {multiTasks.length > 0 && (
          <aside className="notice info">
            已受理 {multiTasks.length} 份材料：
            {multiTasks.map(id => (
              <button key={id} type="button" className="link-btn" style={{ marginLeft: 8 }}
                onClick={() => navigate('/tasks/' + id)}>#{id} 查看进度</button>
            ))}
          </aside>
        )}

        <section className="panel">
          <h2>选择材料</h2>
          <ul className="material-help">
            <li>电子 PDF：推荐从手机银行直接导出，最大 20MB。</li>
            <li>拍照或扫描图片：JPG/PNG，最大 10MB，短边至少 1000 像素；处理后需人工复核。</li>
            <li>截图：可以选择，但来源难以核验，可能无法作为授信依据。</li>
          </ul>
          <p className="muted">实际载体类型、清晰度和文件完整性以后端检查为准。</p>

          <div className={`drop${file ? ' has-file' : ''}`} onDragOver={e => e.preventDefault()} onDrop={dropFile}>
            {files.length > 1 && (
              <div className="multi-files">
                <p className="file-ok" role="status">
                  <span className="file-tick" aria-hidden="true">✓</span>已选择 <strong>{files.length}</strong> 个文件
                </p>
                <ol className="multi-list">
                  {files.map((f, i) => (
                    <li key={f.name + i}>
                      <span className="muted small">{i + 1}.</span>
                      <span className="multi-name">{f.name}</span>
                      <span className="muted small">{formatSize(f.size)}</span>
                      <button type="button" className="link-btn"
                        onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))}>移除</button>
                    </li>
                  ))}
                </ol>
                <p className="muted small">
                  {files.every(f => !/\.pdf$/i.test(f.name))
                    ? '都是图片：会按顺序合成一份材料再解析（适合同一份流水的多张照片）。'
                    : '包含 PDF：每个文件分别受理，生成多条记录。'}
                </p>
              </div>
            )}

            {files.length <= 1 && file ? (
              <div className="file-chosen">
                <p className="file-ok" role="status">
                  <span className="file-tick" aria-hidden="true">✓</span>文件已选择
                  <strong className="file-name">{file.name}</strong>
                </p>
                <p className="file-size">{formatSize(file.size)} · 本地检查通过 · 拖入新文件可替换（可多选）</p>
                <div className="file-actions">
                  <label className="btn ghost">重新选择<input className="file-input" type="file" accept=".pdf,.jpg,.jpeg,.png" multiple onChange={changeFile} /></label>
                  <button className="btn ghost" type="button" onClick={() => { void selectFile(); }}>移除</button>
                </div>
              </div>
            ) : (
              <>
                <h3>{checking ? '正在检查文件…' : '拖拽一份文件到这里'}</h3>
                {checking
                  ? <p className="file-size">{checkingName}</p>
                  : (
                    <>
                      <label className="btn ghost">选择文件<input className="file-input" type="file" accept=".pdf,.jpg,.jpeg,.png" multiple onChange={changeFile} /></label>
                      <p>支持 PDF / JPG / JPEG / PNG</p>
                    </>
                  )}
              </>
            )}
          </div>

          <div aria-live="polite">
            {error && <p className="error" role="alert">{error}</p>}
          </div>

          {needPassword && (
            <label className="field">该文件有打开口令
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="输入口令后再次提交" />
            </label>
          )}

          <details style={{ margin: '8px 0' }}>
            <summary className="muted">补充信息（选填）</summary>
            <div className="controls">
              <label>开始月份<input type="month" max={thisMonth} value={start} onChange={e => setStart(e.target.value)} /></label>
              <label>结束月份<input type="month" max={thisMonth} value={end} onChange={e => setEnd(e.target.value)} /></label>
            </div>
            {periodError && <p className="error" role="alert">{periodError}</p>}
            {start && end && !periodError && (
              <p className="muted">提交期间：{toMonthStart(start)} 至 {toMonthEnd(end)}（按整月）</p>
            )}
          </details>

          <label className="consent consent-row">
            <input type="checkbox" checked={agreed} onChange={e => setAgreed(e.target.checked)} />
            我确认已获授权提交该流水，并同意由银行按授权用途处理。
          </label>

          {file && !periodError && !agreed && (
            <p className="muted">请勾选授权确认后再提交。</p>
          )}

          <button className="btn" type="button" disabled={!canSubmit} onClick={() => { void submit(); }}>
            {submitting ? '提交中…' : '提交材料'}
          </button>
        </section>
      </main>
    </>
  );
}

