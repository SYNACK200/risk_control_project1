import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Stage } from '../components/Stage';
import { openSampleFile } from '../lib/pdf';
import { createEmpty, uid } from '../lib/template';
import { getTemplateById, getTemplateSample, saveTemplateLayout } from '../lib/api';
import type { FieldMapV1, SamplePage, Selection, Tool } from '../lib/types';

/**
 * 改模板的框画范围。
 *
 * 单独一页而不是塞进标注向导：标注向导承担「从零建模板」，框画范围编辑只做一件事——
 * 在当时的样本上调整表格区与列，保存为新版本草稿。混在一起会让两边都难维护。
 */
export function TemplateLayoutPage() {
  const { id } = useParams<{ id: string }>();
  const templateId = Number(id);
  const navigate = useNavigate();

  const [sample, setSample] = useState<SamplePage | null>(null);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [map, setMap] = useState<FieldMapV1>(() => createEmpty());
  const [sel, setSel] = useState<Selection | null>(null);
  const [tool, setTool] = useState<Tool>('table');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [meta, setMeta] = useState<{ bank_code: string; version: number; status: string } | null>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const tpl = await getTemplateById(templateId);
        if (!alive) return;
        setMeta({ bank_code: tpl.bank_code, version: tpl.version, status: tpl.status });
        const file = await getTemplateSample(templateId);
        const opened = await openSampleFile(file);
        if (!alive) return;
        setSample(opened);
        setMap(prev => {
          const next: FieldMapV1 = {
            ...prev,
            bank_code: tpl.bank_code || prev.bank_code,
            page_size: { w: Math.round(opened.width * 100) / 100, h: Math.round(opened.height * 100) / 100 },
            meta: { ...prev.meta, sample_name: 'template-' + templateId },
          };
          const lay = tpl.layout as { tables?: unknown[] } | null;
          if (lay && Array.isArray(lay.tables) && lay.tables.length > 0) {
            next.tables = lay.tables as FieldMapV1['tables'];
          }
          return next;
        });
        const lay = tpl.layout as { tables?: unknown[] } | null;
        if (lay && Array.isArray(lay.tables) && lay.tables.length > 0) {
          setMsg('已载入当前的框画范围。拖动表格区或列，调整后保存为新版本。');
        } else {
          setMsg('这个模板还没存过框画范围。先画一个表格区，再把每一列拖出来。');
        }
      } catch (e) {
        setMsg('载入失败：' + (e instanceof Error ? e.message : String(e)));
      }
    })();
    return () => { alive = false; };
  }, [templateId]);

  function addTable(rect: { x: number; y: number; w: number; h: number }) {
    const t = { id: uid('t'), page, area: rect, headerY: rect.y + 0.02, columns: [] as FieldMapV1['tables'][number]['columns'] };
    setMap(prev => ({ ...prev, tables: [...prev.tables, t] }));
    setSel({ kind: 'table', id: t.id });
  }

  async function save() {
    if (map.tables.length === 0) { setMsg('还没有表格区，无法保存'); return; }
    setBusy(true);
    setMsg('保存中…');
    try {
      const layout = {
        page_size: map.page_size,
        tables: map.tables.map(tb => ({
          page: tb.page, area: tb.area, headerY: tb.headerY,
          columns: tb.columns.map(c => ({ field: c.field, fields: c.fields, x: c.x, w: c.w })),
        })),
      };
      const res = await saveTemplateLayout(templateId, layout, null);
      setMsg('已保存为 v' + res.version + ' 草稿（原版本已停用）。到模板库点「启用」后新上传的流水才用它。');
    } catch (e) {
      setMsg('保存失败：' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <div className="tpl-layout-head">
        <h2>改框画范围</h2>
        <span className="muted small">
          模板 #{templateId}{meta ? ' · ' + meta.bank_code + ' v' + meta.version + '（' + meta.status + '）' : ''}
        </span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button className={'pill-btn' + (tool === 'table' ? ' pill-btn-primary' : '')} type="button"
            onClick={() => setTool('table')}>画表格区</button>
          <button className={'pill-btn' + (tool === 'column' ? ' pill-btn-primary' : '')} type="button"
            onClick={() => setTool('column')}>画列</button>
          <button className="pill-btn" type="button" onClick={() => setZoom(z => Math.max(0.5, Math.round((z - 0.2) * 10) / 10))}>−</button>
          <span className="muted small" style={{ minWidth: 40, textAlign: 'center' }}>{Math.round(zoom * 100)}%</span>
          <button className="pill-btn" type="button" onClick={() => setZoom(z => Math.min(3, Math.round((z + 0.2) * 10) / 10))}>＋</button>
          <button className="btn" type="button" disabled={busy || map.tables.length === 0} onClick={() => { void save(); }}>
            保存为新版本
          </button>
          <button className="link-btn" type="button" onClick={() => navigate('/templates')}>回模板库</button>
        </span>
      </div>

      {msg && <div className="notice info" style={{ margin: '0 18px 8px' }}>{msg}</div>}

      <div className="workspace">
        {sample ? (
          <Stage
            sample={sample}
            page={page}
            zoom={zoom}
            tool={tool}
            map={map}
            sel={sel}
            onSelect={(s2: Selection) => setSel(s2)}
            onDraw={(rect) => addTable(rect)}
            onMove={(kind, tid, rect) => {
              if (kind !== 'table') return;
              setMap(prev => ({ ...prev, tables: prev.tables.map(t => t.id === tid ? { ...t, area: rect } : t) }));
            }}
            onHint={(text: string) => setMsg(text)}
            onColumnResize={(tid, index, x, w) => {
              setMap(prev => ({
                ...prev,
                tables: prev.tables.map(t => t.id !== tid ? t : {
                  ...t,
                  columns: t.columns.map((c, i) => i === index ? { ...c, x, w } : c),
                }),
              }));
            }}
          />
        ) : (
          <div className="stage-wrap"><div className="empty">正在载入样本…</div></div>
        )}
        <div className="side">
          <div className="side-scroll">
            <div className="inspector">
              <h3>表格区（{map.tables.length}）</h3>
              <p className="muted small">
                在样本上拖一个表格区，再拖出每一列；列可以整体拖动、拖左右边缘改宽窄。
              </p>
              {map.tables.map((t, i) => (
                <div key={t.id} className="muted small" style={{ marginTop: 6 }}>
                  表格 {i + 1} · 第 {t.page} 页 · {t.columns.length} 列
                </div>
              ))}
              {page < (sample?.pageCount ?? 1) && (
                <button className="pill-btn" type="button" style={{ marginTop: 8 }} onClick={() => setPage(p => p + 1)}>
                  下一页（第 {page + 1} 页）
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}