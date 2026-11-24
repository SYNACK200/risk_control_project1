import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  getTemplate,
  getTemplateLayout,
  getTemplateLayoutPng,
  getTemplateSample,
  type TemplateDetail,
  type TemplateLayout,
} from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { PdfPageCanvas } from '../../components/PdfPageCanvas';
import { BOX_COLORS, bankLabel, fieldLabel, fromSavedLayout } from '../../components/annotate/types';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';

export default function TemplateLayoutPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const templateId = Number(id);

  const [detail, setDetail] = useState<TemplateDetail | null>(null);
  const [layoutInfo, setLayoutInfo] = useState<TemplateLayout | null>(null);
  const [sampleBytes, setSampleBytes] = useState<ArrayBuffer | null>(null);
  const [sampleMime, setSampleMime] = useState<string>('application/pdf');
  const [fallbackPngUrl, setFallbackPngUrl] = useState<string>('');
  const [pageIndex, setPageIndex] = useState(0);
  const [pageCount, setPageCount] = useState(1);
  const [zoom, setZoom] = useState(1.0);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    let pngObjUrl = '';
    setError('');
    setSampleBytes(null);
    setFallbackPngUrl('');

    Promise.all([getTemplate(templateId), getTemplateLayout(templateId)])
      .then(async ([tpl, lay]) => {
        if (!active) return;
        setDetail(tpl);
        setLayoutInfo(lay);
        const layObj = (tpl.layout || {}) as { page_count?: number };
        setPageCount(Math.max(1, layObj.page_count || lay.layout?.page_count || 1));

        if (tpl.sample_file_id || lay.has_sample) {
          try {
            const blob = await getTemplateSample(templateId);
            if (!active) return;
            setSampleMime(blob.type || 'application/pdf');
            setSampleBytes(await blob.arrayBuffer());
            return;
          } catch {
            // Fall through to backend layout.png
          }
        }
        try {
          const pngBlob = await getTemplateLayoutPng(templateId, 0);
          if (!active) return;
          pngObjUrl = URL.createObjectURL(pngBlob);
          setFallbackPngUrl(pngObjUrl);
        } catch {
          // Neither sample nor PNG available
        }
      })
      .catch((err) => {
        if (active) setError(getErrorMessage(err, 'banker'));
      });

    return () => {
      active = false;
      if (pngObjUrl) URL.revokeObjectURL(pngObjUrl);
    };
  }, [templateId]);

  useEffect(() => {
    if (sampleBytes || !detail) return;
    let active = true;
    let pngObjUrl = '';
    getTemplateLayoutPng(templateId, pageIndex)
      .then((blob) => {
        if (!active) return;
        pngObjUrl = URL.createObjectURL(blob);
        setFallbackPngUrl(pngObjUrl);
      })
      .catch(() => {});
    return () => {
      active = false;
      if (pngObjUrl) URL.revokeObjectURL(pngObjUrl);
    };
  }, [pageIndex, sampleBytes, detail, templateId]);

  if (error && !detail) {
    return (
      <div className="panel wide">
        <Notice>{error}</Notice>
        <Link className="btn btn-ghost" to="/bank/templates">回到列表</Link>
      </div>
    );
  }
  if (!detail) return <p className="muted">加载中…</p>;

  const { regions, columns, singles, customFields } = fromSavedLayout(detail.layout);
  const legacyBoxes = layoutInfo?.layout?.boxes ?? [];
  const pageRegions = regions.filter((r) => r.page === pageIndex);
  const pageRegionIds = new Set(pageRegions.map((r) => r.id));
  const pageCols = columns.filter((c) => pageRegionIds.has(c.regionId));
  const pageSingles = singles.filter((s) => s.page === pageIndex);
  const pageLegacy = legacyBoxes.filter((b) => b.page === pageIndex);

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>
            版式回看：{bankLabel(detail.bank_code)} ({detail.bank_code}) v{detail.version}
          </h1>
          <p className="sub">
            模板 #{detail.id} · {detail.sample_file_id || layoutInfo?.has_sample ? '含原始样本' : '使用示意图预览'} · 共 {pageCount} 页 ·
            当前页 {pageRegions.length} 个表格区、{pageCols.length} 列、{pageSingles.length} 个单值框
          </p>
        </div>
        <div className="filters">
          <Button size="sm" onClick={() => navigate('/bank/annotate?templateId=' + detail.id)}>
            在画布中微调框选
          </Button>
          <Link className="btn btn-ghost" to={'/bank/templates/' + detail.id}>回到详情</Link>
        </div>
      </header>

      {error && <Notice>{error}</Notice>}

      <div className="ann-toolbar" style={{ marginBottom: 12 }}>
        <div className="ann-toolbar-group">
          <button
            type="button"
            className="ann-btn"
            disabled={pageIndex <= 0}
            onClick={() => setPageIndex((p) => Math.max(0, p - 1))}
          >
            ‹ 上一页
          </button>
          <span className="ann-page-num">第 {pageIndex + 1} / {pageCount} 页</span>
          <button
            type="button"
            className="ann-btn"
            disabled={pageIndex >= pageCount - 1}
            onClick={() => setPageIndex((p) => Math.min(pageCount - 1, p + 1))}
          >
            下一页 ›
          </button>
        </div>
        {sampleBytes && (
          <div className="ann-toolbar-group">
            <button type="button" className="ann-btn" onClick={() => setZoom((z) => Math.max(0.6, Number((z - 0.15).toFixed(2))))}>
              −
            </button>
            <span className="ann-zoom-num">{Math.round(zoom * 100)}%</span>
            <button type="button" className="ann-btn" onClick={() => setZoom((z) => Math.min(2.0, Number((z + 0.15).toFixed(2))))}>
              ＋
            </button>
          </div>
        )}
      </div>

      {sampleBytes ? (
        <div className="ann-stage-wrap" style={{ minHeight: 540 }}>
          <PdfPageCanvas
            fileBytes={sampleBytes}
            mimeHint={sampleMime}
            pageIndex={pageIndex}
            zoom={zoom}
            onPageInfo={(info) => setPageCount(Math.max(pageCount, info.pageCount || 1))}
            overlay={
              <div className="ann-overlay" style={{ pointerEvents: 'none' }}>
                {pageRegions.map((reg) => {
                  const rCols = columns.filter((c) => c.regionId === reg.id);
                  return (
                    <div key={reg.id}>
                      <div
                        className="ann-area-box active"
                        style={{
                          left: `${reg.area.x * 100}%`,
                          top: `${reg.area.y * 100}%`,
                          width: `${reg.area.w * 100}%`,
                          height: `${reg.area.h * 100}%`,
                        }}
                      >
                        <span className="ann-tag area">表格区 ({reg.slot})</span>
                      </div>
                      <div
                        className="ann-header-line"
                        style={{
                          left: `${reg.area.x * 100}%`,
                          width: `${reg.area.w * 100}%`,
                          top: `${reg.headerY * 100}%`,
                        }}
                      >
                        <span className="ann-tag header">表头线</span>
                      </div>
                      {rCols.map((col, idx) => {
                        const color = BOX_COLORS[idx % BOX_COLORS.length];
                        return (
                          <div
                            key={col.id}
                            className="ann-col-box"
                            style={{
                              left: `${col.x * 100}%`,
                              width: `${col.w * 100}%`,
                              top: `${reg.area.y * 100}%`,
                              height: `${reg.area.h * 100}%`,
                              borderColor: color,
                              background: `${color}1e`,
                            }}
                          >
                            <span className="ann-tag" style={{ background: color }}>
                              {fieldLabel(col.field, customFields)}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
                {pageSingles.map((s) => (
                  <div
                    key={s.id}
                    className="ann-single-box"
                    style={{
                      left: `${s.x * 100}%`,
                      top: `${s.y * 100}%`,
                      width: `${s.w * 100}%`,
                      height: `${s.h * 100}%`,
                    }}
                  >
                    <span className="ann-tag single">
                      {s.label}{s.value ? `：${s.value}` : ''}
                    </span>
                  </div>
                ))}
                {pageRegions.length === 0 && pageLegacy.map((b, idx) => {
                  const color = BOX_COLORS[idx % BOX_COLORS.length];
                  const pageDim = (
                    layoutInfo?.layout?.pages as Record<string, { width?: number; height?: number }> | undefined
                  )?.[String(pageIndex)];
                  const pageW = pageDim?.width && pageDim.width > 0 ? pageDim.width : (layoutInfo?.layout?.page_size?.w || 595);
                  const pageH = pageDim?.height && pageDim.height > 0 ? pageDim.height : (layoutInfo?.layout?.page_size?.h || 842);
                  const nx0 = b.x0 > 1 ? b.x0 / pageW : b.x0;
                  const nx1 = b.x1 > 1 ? b.x1 / pageW : b.x1;
                  const ny0 = b.y0 > 1 ? b.y0 / pageH : b.y0;
                  const ny1 = b.y1 > 1 ? b.y1 / pageH : b.y1;
                  return (
                    <div
                      key={idx}
                      className="ann-col-box"
                      style={{
                        left: `${nx0 * 100}%`,
                        width: `${Math.max(0.02, nx1 - nx0) * 100}%`,
                        top: `${ny0 * 100}%`,
                        height: `${Math.max(0.03, ny1 - ny0) * 100}%`,
                        borderColor: color,
                        background: `${color}1e`,
                      }}
                    >
                      <span className="ann-tag" style={{ background: color }}>
                        {b.field} ({b.column})
                      </span>
                    </div>
                  );
                })}
              </div>
            }
          />
        </div>
      ) : fallbackPngUrl ? (
        <div className="ann-stage-wrap" style={{ padding: 16 }}>
          <img
            src={fallbackPngUrl}
            alt={`模板 #${detail.id} 版式示意图`}
            style={{ maxWidth: '100%', height: 'auto', border: '1px solid var(--border)', borderRadius: 6 }}
          />
        </div>
      ) : (
        <p className="muted">暂无可渲染的样本或示意图。</p>
      )}

      <section style={{ marginTop: 18 }}>
        <h2>结构明细（共 {regions.length} 个表格区，{columns.length} 列，{singles.length} 个单值框）</h2>
        {columns.length > 0 ? (
          <table className="grid compact">
            <thead>
              <tr><th>所属区域</th><th>字段</th><th>左边界 x</th><th>列宽 w</th><th>页面</th></tr>
            </thead>
            <tbody>
              {columns.map((c) => {
                const reg = regions.find((r) => r.id === c.regionId);
                return (
                  <tr key={c.id}>
                    <td className="small muted">{reg ? `第 ${reg.page + 1} 页 (${reg.slot})` : '—'}</td>
                    <td>{fieldLabel(c.field, customFields)} <span className="small muted">({c.field})</span></td>
                    <td className="small mono">{c.x.toFixed(4)}</td>
                    <td className="small mono">{c.w.toFixed(4)}</td>
                    <td className="small muted">{reg ? reg.page + 1 : 1}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : pageLegacy.length > 0 ? (
          <table className="grid compact">
            <thead><tr><th>字段</th><th>表头列</th><th>页</th><th>范围</th></tr></thead>
            <tbody>
              {legacyBoxes.map((box, index) => (
                <tr key={index}>
                  <td>{box.field}</td>
                  <td className="small muted">{box.column}</td>
                  <td>{box.page + 1}</td>
                  <td className="small mono">
                    x {box.x0.toFixed(3)}–{box.x1.toFixed(3)} · y {box.y0.toFixed(3)}–{box.y1.toFixed(3)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">这份模板还没有保存框选布局，建议点击右上角「在画布中微调框选」补齐。</p>
        )}
      </section>
    </div>
  );
}
