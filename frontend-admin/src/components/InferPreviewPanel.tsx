/**
 * 试解析的多页预览：基准页（你标注的那页）+ 后续每一页的可用情况。
 *
 * 为什么要有它：只看「总笔数 570」看不出模板在后续页还能不能用。
 * 如果第 2 页起列就偏了，真实流水上来一样会错；这一步要能在保存前看出来。
 */
export interface PreviewPage {
  page_no: number;
  rows: number;
  header_found: boolean;
}

export interface PreviewPayload {
  txn_count?: number;
  page_count?: number;
  base_page?: number;
  pages?: PreviewPage[];
  error?: string;
}

export function InferPreviewPanel({ preview }: { preview: PreviewPayload | null | undefined }) {
  if (!preview) return null;
  if (preview.error) {
    return <div className="notice error">试跑失败：{preview.error}</div>;
  }
  const pages = preview.pages ?? [];
  const base = preview.base_page ?? 0;
  const empty = pages.filter(p => p.page_no !== base && p.rows === 0);
  const weak = pages.filter(p => p.page_no !== base && p.rows > 0 && !p.header_found);

  return (
    <section className="infer-preview">
      <div className="infer-preview-head">
        <strong>多页试跑</strong>
        <span className="muted small">
          共 {preview.page_count ?? pages.length} 页 · {preview.txn_count ?? 0} 笔 ·
          基准页第 {base + 1} 页（你标注的那页）
        </span>
      </div>

      {(empty.length > 0 || weak.length > 0) && (
        <div className="notice warn" style={{ margin: '0 0 8px' }}>
          {empty.length > 0 && <div>有 {empty.length} 页没解析出交易（第 {empty.slice(0, 5).map(p => p.page_no + 1).join('、')} 页）。</div>}
          {weak.length > 0 && <div>有 {weak.length} 页没识别到页眉（第 {weak.slice(0, 5).map(p => p.page_no + 1).join('、')} 页），可能是版式在中途变了。</div>}
        </div>
      )}

      <div className="infer-preview-grid">
        {pages.map(p => {
          const isBase = p.page_no === base;
          const bad = p.rows === 0;
          return (
            <div
              key={p.page_no}
              className={'pv-cell' + (isBase ? ' base' : '') + (bad ? ' bad' : '') + (!p.header_found && !bad ? ' weak' : '')}
              title={isBase ? '基准页（你标注的那页）' : (!p.header_found ? '未识别到页眉' : '')}
            >
              <span className="pv-no">{p.page_no + 1}</span>
              <span className="pv-rows">{p.rows}</span>
            </div>
          );
        })}
      </div>
      <p className="muted small" style={{ marginTop: 6 }}>
        每格是「页号 / 该页解析笔数」。蓝框＝基准页；灰掉＝该页没出交易；虚线＝没识别到页眉。
      </p>
    </section>
  );
}
