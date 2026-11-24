import { type TemplatePreview } from '../../api/banker';
import { Button } from '../../ui/Button';
import { labelOf } from '../../lib/columns';

type Props = {
  preview: TemplatePreview | null;
  onClose: () => void;
  onSwapAmountBalance?: () => void;
};

export function PreviewDrawer({ preview, onClose, onSwapAmountBalance }: Props) {
  if (!preview) return null;

  const hasIssues = preview.missing_columns.length > 0 || preview.empty_columns.length > 0;
  const mayNeedSwap = Boolean(
    onSwapAmountBalance &&
      (preview.warnings.some((w) => /余额|反转|倒置|相差较大/.test(w)) || preview.txn_count === 0),
  );
  const meta = preview.meta || {};
  const extraMeta = preview.extra_meta || {};
  const knownKeys = new Set(['account_no', 'account_name', 'bank_branch', 'account_type', 'currency', 'period_start', 'period_end']);
  const metaPairs = ([
    ['卡号/账号', meta.account_no],
    ['户名', meta.account_name],
    ['开户行', meta.bank_branch],
    ['账户类型', meta.account_type],
    ['币种', meta.currency],
    ['期初~期末', meta.period_start && meta.period_end ? `${meta.period_start} ~ ${meta.period_end}` : meta.period_start || meta.period_end],
    ...Object.entries(extraMeta).filter(([k]) => !knownKeys.has(k)),
  ] as [string, unknown][]).filter(([, v]) => Boolean(v));

  return (
    <section className="ann-preview-panel">
      <div className="ann-preview-head">
        <div>
          <strong>实时试跑结果</strong>
          <span className="ann-preview-summary">
            共读出 <b>{preview.txn_count}</b> 笔流水 · {preview.page_count} 页
            {hasIssues ? ' · 有缺漏提示' : ' · 核心字段完整'}
          </span>
        </div>
        <div className="filters">
          {mayNeedSwap && onSwapAmountBalance && (
            <Button size="sm" variant="secondary" onClick={onSwapAmountBalance}>
              对调金额与余额列重试
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onClose}>
            收起试跑结果
          </Button>
        </div>
      </div>

      {hasIssues && (
        <div className="ann-preview-warn">
          {preview.missing_columns.length > 0 && (
            <div>未映射必需字段：{preview.missing_columns.map(labelOf).join('、')}</div>
          )}
          {preview.empty_columns.length > 0 && (
            <div>以下必需字段有框但未读到有效值：{preview.empty_columns.map(labelOf).join('、')}</div>
          )}
        </div>
      )}

      {preview.warnings.length > 0 && (
        <div className="ann-preview-notes">
          {preview.warnings.map((w, idx) => (
            <span key={idx} className="pill warn">
              {w}
            </span>
          ))}
        </div>
      )}

      {metaPairs.length > 0 && (
        <div className="ann-meta-chips">
          {metaPairs.map(([k, v]) => (
            <span key={String(k)} className="ann-meta-chip">
              {String(k)}：<b>{String(v)}</b>
            </span>
          ))}
        </div>
      )}

      {preview.pages.length > 0 && (
        <div className="ann-page-grid">
          {preview.pages.map((p) => (
            <span key={p.page_no} className={p.rows > 0 ? 'ann-pg-badge ok' : 'ann-pg-badge'}>
              第 {p.page_no} 页：{p.rows} 笔{p.header_found ? ' · 有页眉' : ''}
            </span>
          ))}
        </div>
      )}

      <div className="table-scroll">
        <table className="table compact">
          <thead>
            <tr>
              <th>页</th>
              <th>交易日期</th>
              <th>摘要</th>
              <th>对方户名</th>
              <th>方向</th>
              <th>交易金额</th>
              <th>余额</th>
              <th>附加自定义列</th>
            </tr>
          </thead>
          <tbody>
            {preview.rows.length === 0 ? (
              <tr>
                <td colSpan={8} className="empty-cell">
                  暂未解析出交易行，请调整表格区（紫框）、表头线（琥珀线）与列框范围后再试。
                </td>
              </tr>
            ) : (
              preview.rows.map((r, i) => (
                <tr key={i}>
                  <td>P{r.page_no}</td>
                  <td>{r.txn_date || '—'}</td>
                  <td>{r.summary || '—'}</td>
                  <td>{r.counterparty || '—'}</td>
                  <td>{r.direction === 'in' ? '收入' : r.direction === 'out' ? '支出' : '—'}</td>
                  <td className="num">{r.amount || '—'}</td>
                  <td className="num">{r.balance || '—'}</td>
                  <td>
                    {r.extra && Object.keys(r.extra).length > 0
                      ? Object.entries(r.extra)
                          .map(([k, v]) => `${k}:${v}`)
                          .join(' | ')
                      : '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
