import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  disableTemplate,
  duplicateTemplate,
  exportTemplateBlob,
  getTemplate,
  getTemplateLayoutPng,
  getTemplateSample,
  getTemplateStats,
  previewTemplate,
  publishTemplate,
  updateTemplateRequired,
  type TemplateDetail,
  type TemplatePreview,
  type TemplateStats,
} from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { getUser } from '../../auth/store';
import { bankLabel } from '../../components/annotate/types';
import { labelOf } from '../../lib/columns';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';

const CANDIDATES = [
  'txn_date',
  'trade_time',
  'reference_no',
  'summary',
  'counterparty_name',
  'direction',
  'amount',
  'amount_in',
  'amount_out',
  'balance',
  'account_no',
];

export default function TemplateDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const templateId = Number(id);
  const isAdmin = Boolean(getUser()?.is_admin);

  const [template, setTemplate] = useState<TemplateDetail | null>(null);
  const [stats, setStats] = useState<TemplateStats | null>(null);
  const [required, setRequired] = useState<string[]>([]);
  const [preview, setPreview] = useState<TemplatePreview | null>(null);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [layoutImgUrl, setLayoutImgUrl] = useState<string | null>(null);

  const loadDetail = () => {
    setError('');
    Promise.all([getTemplate(templateId), getTemplateStats(templateId)])
      .then(([detail, statistics]) => {
        setTemplate(detail);
        setStats(statistics);
        setRequired(detail.required_fields ?? ['txn_date', 'amount', 'balance']);
      })
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  };

  useEffect(() => {
    setMessage('');
    loadDetail();
    let active = true;
    let objUrl: string | null = null;
    getTemplateLayoutPng(templateId, 0)
      .then((blob) => {
        if (!active) return;
        objUrl = URL.createObjectURL(blob);
        setLayoutImgUrl(objUrl);
      })
      .catch(() => setLayoutImgUrl(null));
    return () => {
      active = false;
      if (objUrl) URL.revokeObjectURL(objUrl);
    };
  }, [templateId]);

  async function onPublish() {
    setBusy(true);
    setError('');
    try {
      await publishTemplate(templateId);
      setMessage('已启用该模板（同银行其他启用版本已自动停用）。');
      loadDetail();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  async function onDisable() {
    setBusy(true);
    setError('');
    try {
      await disableTemplate(templateId);
      setMessage('已停用该模板。');
      loadDetail();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  async function onDuplicate() {
    setBusy(true);
    setError('');
    try {
      const res = await duplicateTemplate(templateId);
      navigate('/bank/templates/' + res.id);
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  async function runPreviewBlob(blob: Blob) {
    setBusy(true);
    setError('');
    setMessage('');
    setPreview(null);
    try {
      const result = await previewTemplate(templateId, blob, password || undefined);
      setPreview(result);
    } catch (err) {
      const code = (err as { code?: string }).code;
      if (code === 'E_ENCRYPT') setMessage('这份 PDF 设有打开口令，填在下方再试一次。');
      else setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  async function onPreviewSample() {
    setBusy(true);
    setError('');
    try {
      const blob = await getTemplateSample(templateId);
      await runPreviewBlob(blob);
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
      setBusy(false);
    }
  }

  async function onExport() {
    try {
      const blob = await exportTemplateBlob(templateId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `template-${template?.bank_code ?? templateId}-v${template?.version ?? 1}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    }
  }

  async function saveRequired() {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const result = await updateTemplateRequired(templateId, required);
      setMessage(`必需列已保存为模板 #${result.id}（v${result.version} 草稿，旧版本保留）。`);
      navigate('/bank/templates/' + result.id, { replace: true });
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  if (error && !template) return <div className="panel"><Notice>{error}</Notice></div>;
  if (!template) return <p className="muted">加载中…</p>;

  const mapped = Object.keys(template.field_map ?? {});
  const layObj = (template.layout || {}) as { tables?: unknown[]; meta_boxes?: unknown[]; custom_fields?: { key: string; label: string }[] };
  const customMap = Object.fromEntries((layObj.custom_fields || []).map((c) => [c.key, c.label]));
  const fieldName = (k: string) => customMap[k] ?? labelOf(k);

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>
            {bankLabel(template.bank_code)} ({template.bank_code}) v{template.version}
          </h1>
          <p className="sub">
            模板 #{template.id} · 状态 {template.status === 'enabled' ? '在用' : template.status === 'draft' ? '草稿' : '停用'}
            {' '}· 已标 {mapped.length} 列
            {layObj.tables?.length ? ` · ${layObj.tables.length} 个表格区框选` : ''}
            {template.sample_file_id ? ' · 含原件样本' : ' · 暂无原件样本'}
          </p>
        </div>
        <div className="filters">
          <Button size="sm" onClick={() => navigate('/bank/annotate?templateId=' + template.id)}>
            在画布中编辑框选
          </Button>
          {isAdmin && template.status !== 'enabled' && (
            <Button size="sm" disabled={busy} onClick={() => void onPublish()}>
              启用此版本
            </Button>
          )}
          {isAdmin && template.status === 'enabled' && (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => void onDisable()}>
              停用
            </Button>
          )}
          {isAdmin && (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => void onDuplicate()}>
              复制为新草稿
            </Button>
          )}
          <Link className="btn btn-ghost" to={'/bank/templates/' + template.id + '/layout'}>看全页版式图</Link>
          <button type="button" className="btn btn-ghost" onClick={() => void onExport()}>导出 JSON</button>
          <Link className="btn btn-ghost" to="/bank/templates">回到列表</Link>
        </div>
      </header>

      {error ? <Notice>{error}</Notice> : null}
      {message ? <Notice tone="ok">{message}</Notice> : null}

      <section className="score-row">
        <div className="score"><span className="score-value">{stats?.tasks_total ?? 0}</span><span className="muted small">命中任务</span></div>
        <div className="score"><span className="score-value">{stats?.success_rate == null ? '—' : Math.round(stats.success_rate * 100) + '%'}</span><span className="muted small">成功率</span></div>
        <div className="score"><span className="score-value">{stats?.avg_txn_count ?? '—'}</span><span className="muted small">平均笔数</span></div>
        <div className="score"><span className="score-value">{stats?.zero_txn_tasks ?? 0}</span><span className="muted small">零笔任务</span></div>
      </section>

      {layoutImgUrl && (
        <section>
          <h2>首页版式框选示意图</h2>
          <img
            src={layoutImgUrl}
            alt="模板框选示意图"
            style={{ maxWidth: '100%', maxHeight: 420, border: '1px solid var(--border, #d8dee9)', borderRadius: 8 }}
          />
        </section>
      )}

      <section>
        <h2>试跑（不落库）</h2>
        <p className="muted small">
          拿一份同版式的文件试一遍：能出几笔、每页各几笔、单值（卡号/户名）与必需列是否完整。试跑不通先别启用。
        </p>
        <div className="try-row">
          <input
            type="file"
            accept=".pdf,image/png,image/jpeg,image/webp"
            onChange={(event) => {
              const f = event.target.files?.[0];
              if (f) void runPreviewBlob(f);
            }}
          />
          <input
            type="password"
            placeholder="口令（加密件才填）"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {template.sample_file_id ? (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => void onPreviewSample()}>
              用自带样本试跑
            </Button>
          ) : null}
          {busy ? <span className="muted small">试跑中…</span> : null}
        </div>

        {preview ? (
          <div className="try-result">
            <div className="score-row">
              <div className="score"><span className="score-value">{preview.txn_count}</span><span className="muted small">读出笔数</span></div>
              <div className="score"><span className="score-value">{preview.page_count}</span><span className="muted small">页数</span></div>
              <div className="score"><span className="score-value">{preview.present_columns.length}</span><span className="muted small">命中必需列</span></div>
              <div className="score">
                <span className={'score-value' + (preview.missing_columns.length || preview.empty_columns.length ? ' bad' : '')}>
                  {preview.missing_columns.length + preview.empty_columns.length}
                </span>
                <span className="muted small">缺漏项</span>
              </div>
            </div>

            {preview.meta && (preview.meta.account_no || preview.meta.account_name || preview.meta.bank_branch || preview.meta.currency || (preview.extra_meta && Object.keys(preview.extra_meta).length > 0)) ? (
              <div className="ann-meta-chips" style={{ marginBottom: 10 }}>
                {preview.meta.account_no && <span className="ann-meta-chip">卡号/账号：<b>{preview.meta.account_no}</b></span>}
                {preview.meta.account_name && <span className="ann-meta-chip">户名：<b>{preview.meta.account_name}</b></span>}
                {preview.meta.bank_branch && <span className="ann-meta-chip">开户行：<b>{preview.meta.bank_branch}</b></span>}
                {preview.meta.account_type && <span className="ann-meta-chip">账户类型：<b>{preview.meta.account_type}</b></span>}
                {preview.meta.currency && <span className="ann-meta-chip">币种：<b>{preview.meta.currency}</b></span>}
                {Object.entries(preview.extra_meta || {}).map(([k, v]) => (
                  <span key={k} className="ann-meta-chip">{fieldName(k)}：<b>{v}</b></span>
                ))}
              </div>
            ) : null}

            {preview.missing_columns.length || preview.empty_columns.length ? (
              <Notice>
                未读到：{preview.missing_columns.concat(preview.empty_columns).map(fieldName).join('、')}
                。未标注的列点右上角「在画布中编辑框选」补上；已标但未读到，多半是列框位置偏了或表头线太低。
              </Notice>
            ) : (
              <p className="muted small">必需列均已命中且有值。</p>
            )}

            {preview.warnings.length ? (
              <ul className="plain">
                {preview.warnings.map((item, index) => <li key={index}>{item}</li>)}
              </ul>
            ) : null}

            <table className="grid compact">
              <thead><tr><th>页码</th><th>笔数</th><th>页眉单值</th></tr></thead>
              <tbody>
                {preview.pages.map((page) => (
                  <tr key={page.page_no}>
                    <td>第 {page.page_no} 页</td>
                    <td>{page.rows}</td>
                    <td className="small muted">{page.header_found ? '识别到' : '未识别'}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <table className="grid compact">
              <thead>
                <tr><th>日期</th><th>方向</th><th>金额</th><th>余额</th><th>摘要</th><th>对方户名</th><th>页</th></tr>
              </thead>
              <tbody>
                {preview.rows.map((row, index) => (
                  <tr key={index}>
                    <td className="small">{row.txn_date ?? '—'}</td>
                    <td className="small">{row.direction === 'in' ? '入' : row.direction === 'out' ? '出' : '—'}</td>
                    <td className="mono">{row.amount ?? '—'}</td>
                    <td className="small muted mono">{row.balance ?? '—'}</td>
                    <td className="small">{row.summary ?? ''}</td>
                    <td className="small">{row.counterparty ?? '—'}</td>
                    <td className="small muted">{row.page_no || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section>
        <h2>必需列（{required.length}）</h2>
        <p className="muted small">
          勾上「这份版式一定有的列」。解析时若没读到，报告会明示缺列原因，避免静默漏算指标。
        </p>
        <div className="chips">
          {CANDIDATES.map((field) => {
            const on = required.includes(field);
            return (
              <button
                key={field}
                type="button"
                className={'chip' + (on ? ' chip-on' : '')}
                disabled={!isAdmin}
                onClick={() => setRequired(on ? required.filter((f) => f !== field) : [...required, field])}
              >
                {fieldName(field)}
              </button>
            );
          })}
        </div>
        {isAdmin ? (
          <div className="actions">
            <Button onClick={() => void saveRequired()} disabled={busy}>保存必需列（出新版本）</Button>
          </div>
        ) : (
          <p className="muted small">只读（需管理员）</p>
        )}
      </section>

      <section>
        <h2>字段映射（{mapped.length} 项）</h2>
        <table className="grid compact">
          <thead><tr><th>规范字段</th><th>对应列名</th><th>必需</th></tr></thead>
          <tbody>
            {Object.entries(template.field_map ?? {}).map(([field, target]) => (
              <tr key={field}>
                <td title={field}>{fieldName(field)}</td>
                <td className="small muted">{String(target)}</td>
                <td className="small muted">{required.includes(field) ? '是' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
