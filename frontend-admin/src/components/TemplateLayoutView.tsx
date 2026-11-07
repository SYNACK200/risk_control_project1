import { useEffect, useState } from 'react';
import { getTemplateLayout, getTemplateLayoutPng, type TemplateLayoutPayload } from '../lib/api';

const PALETTE = ['#2563eb', '#7c3aed', '#0891b2', '#c2410c', '#15803d', '#be123c', '#4d7c0f', '#a21caf'];

interface LayoutTable {
  page?: number;
  area?: { x: number; y: number; w: number; h: number };
  headerY?: number;
  columns?: { field?: string; x: number; w: number }[];
}
interface LayoutV1 {
  tables?: LayoutTable[];
  page_size?: { w: number; h: number };
}

/**
 * 模板详情里的「当时的框选」。
 *
 * 坑：这里原来读 layout.boxes（更早的字段框格式），而现在的 layout 存的是
 * tables + columns，boxes 永远是空数组——结果只显示一张空白样本图，一个框都没有。
 * 现在按 tables 画表格区、按 columns 画列边界，并把每页的框分开显示。
 */
export function TemplateLayoutView({ templateId }: { templateId: number }) {
  const [data, setData] = useState<TemplateLayoutPayload | null>(null);
  const [url, setUrl] = useState('');
  const [page, setPage] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true); setError(''); setUrl(''); setPage(0);
    getTemplateLayout(templateId)
      .then(d => { if (alive) setData(d); })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [templateId]);

  useEffect(() => {
    if (!data?.has_sample) return;
    let alive = true;
    let objectUrl = '';
    getTemplateLayoutPng(templateId, page)
      .then(blob => { objectUrl = URL.createObjectURL(blob); if (alive) setUrl(objectUrl); })
      .catch(() => { if (alive) setUrl(''); });
    return () => { alive = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [templateId, page, data?.has_sample]);

  if (loading) return <div className="muted small">正在读取当时的框选…</div>;
  if (error) return <div className="me-warn">读取失败：{error}</div>;
  if (!data) return null;

  const lay = (data.layout ?? null) as LayoutV1 | null;
  const tables = lay?.tables ?? [];
  if (!data.has_sample || !lay || tables.length === 0) {
    return (
      <div className="layout-empty">
        <div className="muted">这个模板还没有保存过框画范围，所以没有可回看的框。</div>
        <div className="muted small">点上面「改框画范围」，在当时的样本上画一次表格区和每一列，保存后这里就能看到。</div>
      </div>
    );
  }

  const pageNos = [...new Set(tables.map(t => t.page ?? 0))].sort((a, b) => a - b);
  // 该页画过就用该页的；没画过就用第 0 页的（版式一致时后续页沿用同一套框）
  const shown = tables.filter(t => (t.page ?? 0) === page);
  const effective = shown.length > 0 ? shown : tables.filter(t => (t.page ?? 0) === 0);
  const size = lay.page_size ?? { w: 1, h: 1 };
  const pct = (v: number) => (v * 100).toFixed(2) + '%';

  return (
    <div className="layout-view">
      <div className="layout-head">
        <strong>当时的框选</strong>
        <span className="muted small">
          {effective.length} 个表格区 · {effective.reduce((n, t) => n + (t.columns?.length ?? 0), 0)} 列
          {shown.length === 0 && ' · 本页未单独画过，沿用第 1 页的框'}
        </span>
        {pageNos.length > 1 && (
          <span className="layout-pager">
            {pageNos.map(n => (
              <button key={n} type="button" className={'pill-btn' + (n === page ? ' pill-btn-primary' : '')}
                onClick={() => setPage(n)}>第 {n + 1} 页</button>
            ))}
          </span>
        )}
      </div>

      <div className="layout-body">
        <div className="layout-image" style={{ position: 'relative' }}>
          {url ? <img src={url} alt={'模板 ' + templateId + ' 第 ' + (page + 1) + ' 页'} style={{ display: 'block', width: '100%' }} />
               : <div className="muted small">正在渲染样本页…</div>}
          {effective.map((t, ti) => {
            const a = t.area;
            if (!a) return null;
            const color = PALETTE[ti % PALETTE.length];
            return (
              <div key={ti} style={{ position: 'absolute', left: pct(a.x), top: pct(a.y), width: pct(a.w), height: pct(a.h),
                border: '2px solid ' + color, borderRadius: 3, pointerEvents: 'none', boxSizing: 'border-box' }}>
                <span style={{ position: 'absolute', top: -18, left: -2, background: color, color: '#fff',
                  fontSize: 11, padding: '1px 5px', borderRadius: 3, whiteSpace: 'nowrap' }}>
                  表格区 · {t.columns?.length ?? 0} 列
                </span>
                {(t.columns ?? []).map((c, ci) => (
                  <div key={ci} title={c.field || '未指定字段'} style={{ position: 'absolute',
                    left: ((c.x - a.x) / (a.w || 1)) * 100 + '%', width: (c.w / (a.w || 1)) * 100 + '%',
                    top: 0, bottom: 0, borderLeft: '1px dashed rgba(37,99,235,.75)',
                    borderRight: '1px solid rgba(37,99,235,.35)', pointerEvents: 'none' }} />
                ))}
              </div>
            );
          })}
        </div>
      </div>
      <p className="muted small" style={{ marginTop: 6 }}>
        上图是保存这份模板时在样本上画的表格区（实线框）与列边界（虚线）。页面尺寸 {size.w} × {size.h} pt。
      </p>
    </div>
  );
}
