import { useEffect, useRef, useState } from 'react';
import type { FieldMapV1, Rect, SamplePage, Selection, Tool } from '../lib/types';
import { isUsableRect, rectFromPoints, round4 } from '../lib/template';
import { labelOf } from '../lib/fields';

interface Props {
  sample: SamplePage;
  page: number;
  zoom: number;
  tool: Tool;
  map: FieldMapV1;
  sel: Selection;
  onDraw: (rect: Rect) => void;
  onSelect: (s: Selection) => void;
  onMove: (kind: 'meta' | 'table', id: string, rect: Rect) => void;
  /** 拖动列边界：newX/newW 为相对页面的 0–1 比例。 */
  onColumnResize?: (tableId: string, index: number, x: number, w: number) => void;
  onHint: (text: string) => void;
}

/** 八个方向的缩放手柄。原来只有右下角一个，用户根本调不动大框。 */
type Dir = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w';
const DIRS: Dir[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];

type Drag =
  | { mode: 'create'; start: { x: number; y: number }; rect: Rect }
  | { mode: 'move'; kind: 'meta' | 'table'; id: string; start: { x: number; y: number }; origin: Rect }
  | { mode: 'resize'; kind: 'meta' | 'table'; id: string; origin: Rect; dir: Dir }
  | { mode: 'col-move'; tableId: string; index: number; startX: number; originX: number; originW: number; areaX: number; areaW: number }
  | { mode: 'col-left'; tableId: string; index: number; startX: number; originX: number; originW: number }
  | { mode: 'col-right'; tableId: string; index: number; startX: number; originX: number; originW: number }
  | null;

export function Stage(p: Props) {
  /** 八个方向的缩放手柄。只有右下角一个时，用户想拉大左边或上边完全没办法。 */
  function renderHandles(kind: 'meta' | 'table', id: string, origin: Rect) {
    return DIRS.map(dir => (
      <span
        key={dir}
        className={'handle dir-' + dir}
        title="拖动可调整边框"
        onPointerDown={ev => {
          ev.stopPropagation();
          ev.preventDefault();
          setDrag({ mode: 'resize', kind, id, origin, dir });
          try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch { /* 合成事件没有真实 pointer id，忽略 */ }
        }}
      />
    ));
  }

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const holderRef = useRef<HTMLDivElement | null>(null);
  const [drag, setDrag] = useState<Drag>(null);
  const [renderError, setRenderError] = useState('');
  const renderSeq = useRef(0);
  const renderChain = useRef<Promise<void>>(Promise.resolve());

  // pdfjs 禁止同一 canvas 并发 render（StrictMode 会双跑 effect），串行并对过期任务短路
  useEffect(() => {
    const seq = ++renderSeq.current;
    const target = canvasRef.current;
    if (!target) return;
    setRenderError('');
    renderChain.current = renderChain.current
      .then(() => {
        if (seq !== renderSeq.current) return;
        return p.sample.render(p.page, target, 780 * p.zoom);
      })
      .catch((err: unknown) => {
        if (seq !== renderSeq.current) return;
        const msg = err instanceof Error ? err.message : String(err);
        setRenderError(`第 ${p.page} 页渲染失败：${msg}`);
      });
  }, [p.sample, p.page, p.zoom]);

  function toRel(e: { clientX: number; clientY: number }): { x: number; y: number } {
    const rect = holderRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return { x: 0, y: 0 };
    return {
      x: Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)),
      y: Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height)),
    };
  }

  function onBackgroundDown(e: React.PointerEvent<HTMLDivElement>) {
    if (e.button !== 0) return;
    if (p.tool === 'column') {
      const hasTable = p.sel && (p.sel.kind === 'table' || p.sel.kind === 'column');
      if (!hasTable) {
        p.onHint('画列之前先选中一个表格区：点一下紫色的表格区，再拖出列边界');
        return;
      }
    }
    const start = toRel(e);
    setDrag({ mode: 'create', start, rect: { x: round4(start.x), y: round4(start.y), w: 0, h: 0 } });
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!drag) return;
    const now = toRel(e);
    if (drag.mode === 'create') {
      setDrag({ ...drag, rect: rectFromPoints(drag.start.x, drag.start.y, now.x, now.y) });
      return;
    }
    if (drag.mode === 'move') {
      const dx = now.x - drag.start.x;
      const dy = now.y - drag.start.y;
      const nx = Math.min(1 - drag.origin.w, Math.max(0, drag.origin.x + dx));
      const ny = Math.min(1 - drag.origin.h, Math.max(0, drag.origin.y + dy));
      const rect = { x: round4(nx), y: round4(ny), w: drag.origin.w, h: drag.origin.h };
      p.onMove(drag.kind, drag.id, rect);
      return;
    }
    if (drag.mode === 'col-move') {
      if (!p.onColumnResize) return;
      const dx = now.x - drag.startX;
      const minX = drag.areaX;
      const maxX = drag.areaX + drag.areaW - drag.originW;
      const nx = Math.min(maxX, Math.max(minX, drag.originX + dx));
      p.onColumnResize(drag.tableId, drag.index, nx, drag.originW);
      return;
    }
    if (drag.mode === 'col-left' || drag.mode === 'col-right') {
      if (!p.onColumnResize) return;
      const dx = now.x - drag.startX;
      const minW = 0.004;
      if (drag.mode === 'col-right') {
        const w = Math.max(minW, drag.originW + dx);
        p.onColumnResize(drag.tableId, drag.index, drag.originX, Math.min(w, 1 - drag.originX));
      } else {
        const nx = Math.min(drag.originX + drag.originW - minW, Math.max(0, drag.originX + dx));
        const w = drag.originX + drag.originW - nx;
        p.onColumnResize(drag.tableId, drag.index, nx, w);
      }
      return;
    }
    if (drag.mode === 'resize') {
      const o = drag.origin;
      const MIN = 0.004;
      let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
      if (drag.dir.includes('w')) x1 = Math.min(Math.max(0, now.x), x2 - MIN);
      if (drag.dir.includes('e')) x2 = Math.max(Math.min(1, now.x), x1 + MIN);
      if (drag.dir.includes('n')) y1 = Math.min(Math.max(0, now.y), y2 - MIN);
      if (drag.dir.includes('s')) y2 = Math.max(Math.min(1, now.y), y1 + MIN);
      p.onMove(drag.kind, drag.id, { x: x1, y: y1, w: x2 - x1, h: y2 - y1 });
    }
  }

  function onPointerUp() {
    if (drag?.mode === 'create') {
      if (isUsableRect(drag.rect)) p.onDraw(drag.rect);
      else p.onHint('框太小，已忽略。拖出一个至少 0.2% 见方的框。');
    }
    setDrag(null);
  }

  const boxes = p.map.meta_boxes.filter(b => b.page === p.page);
  const tables = p.map.tables.filter(t => t.page === p.page);

  return (
    <div className="stage-wrap">
      <div>
        {renderError && <div className="notice error">{renderError}</div>}
        <div
          className="page-holder"
          ref={holderRef}
          style={{ width: Math.round(780 * p.zoom) + 'px' }}
        >
          <canvas ref={canvasRef} />
          <div
            className="overlay"
            onPointerDown={onBackgroundDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
          >
            {tables.map(t => {
              const selected = p.sel?.kind === 'table' && p.sel.id === t.id;
              return (
                <div
                  key={t.id}
                  className={`box table ${selected ? 'selected' : ''}`}
                  style={{ left: `${t.area.x * 100}%`, top: `${t.area.y * 100}%`, width: `${t.area.w * 100}%`, height: `${t.area.h * 100}%` }}
                  onPointerDown={ev => {
                    // 画列/画框模式下放行：让 overlay 去画，而不是拖表格区
                    if (p.tool !== 'select') return;
                    ev.stopPropagation();
                    p.onSelect({ kind: 'table', id: t.id });
                    const start = toRel(ev);
                    setDrag({ mode: 'move', kind: 'table', id: t.id, start, origin: t.area });
                    try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch { /* 合成事件没有真实 pointer id，忽略 */ }
                  }}
                >
                  <span className="box-label">表格区 · {t.columns.length} 列</span>
                  {selected && renderHandles('table', t.id, t.area)}
                  {t.columns.map((col, idx) => {
                    const colSel = p.sel?.kind === 'column' && p.sel.tableId === t.id && p.sel.index === idx;
                    return (
                      <div
                        key={`${t.id}-c${idx}`}
                        className={`box column ${colSel ? 'selected' : ''} ${col.field ? '' : 'unassigned'}`}
                        style={{ left: `${(col.x - t.area.x) / t.area.w * 100}%`, top: 0, width: `${col.w / t.area.w * 100}%`, height: '100%' }}
                        onPointerDown={ev => {
                          // 画列/画框模式下必须放行：否则用户想在已有列之间再画一条，
                          // 点下去被当成「拖动这一列」，永远加不上新列。
                          if (p.tool !== 'select') return;
                          ev.stopPropagation();
                          p.onSelect({ kind: 'column', tableId: t.id, index: idx });
                          if (!p.onColumnResize) return;
                          setDrag({ mode: 'col-move', tableId: t.id, index: idx, startX: toRel(ev).x,
                                    originX: col.x, originW: col.w, areaX: t.area.x, areaW: t.area.w });
                          try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch { /* 合成事件没有真实 pointer id，忽略 */ }
                        }}
                      >
                        <span className="box-label">{col.field ? labelOf(col.field, p.map.custom_fields) : '未指定'}</span>
                        {p.onColumnResize && (
                          <>
                            <span
                              className="col-handle left"
                              title="拖动调整左边界"
                              onPointerDown={ev => {
                                ev.stopPropagation();
                                setDrag({ mode: 'col-left', tableId: t.id, index: idx, startX: toRel(ev).x, originX: col.x, originW: col.w });
                                try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch { /* 合成事件没有真实 pointer id，忽略 */ }
                              }}
                            />
                            <span
                              className="col-handle right"
                              title="拖动调整右边界"
                              onPointerDown={ev => {
                                ev.stopPropagation();
                                setDrag({ mode: 'col-right', tableId: t.id, index: idx, startX: toRel(ev).x, originX: col.x, originW: col.w });
                                try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch { /* 合成事件没有真实 pointer id，忽略 */ }
                              }}
                            />
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}

            {boxes.map(b => {
              const selected = p.sel?.kind === 'meta' && p.sel.id === b.id;
              return (
                <div
                  key={b.id}
                  className={`box ${selected ? 'selected' : ''} ${b.field ? '' : 'unassigned'}`}
                  style={{ left: `${b.rect.x * 100}%`, top: `${b.rect.y * 100}%`, width: `${b.rect.w * 100}%`, height: `${b.rect.h * 100}%` }}
                  onPointerDown={ev => {
                    ev.stopPropagation();
                    p.onSelect({ kind: 'meta', id: b.id });
                    const start = toRel(ev);
                    setDrag({ mode: 'move', kind: 'meta', id: b.id, start, origin: b.rect });
                    try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch { /* 合成事件没有真实 pointer id，忽略 */ }
                  }}
                >
                  <span className="box-label">{b.field ? labelOf(b.field, p.map.custom_fields) : '未指定字段'}</span>
                  {selected && (
                    <span
                      className="handle dir-se"
                      onPointerDown={ev => {
                        ev.stopPropagation();
                        setDrag({ mode: 'resize', kind: 'meta', id: b.id, origin: b.rect, dir: 'se' });
                        try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch { /* 合成事件没有真实 pointer id，忽略 */ }
                      }}
                    />
                  )}
                </div>
              );
            })}

            {drag?.mode === 'create' && (
              <div
                className="box"
                style={{ left: `${drag.rect.x * 100}%`, top: `${drag.rect.y * 100}%`, width: `${drag.rect.w * 100}%`, height: `${drag.rect.h * 100}%`, pointerEvents: 'none' }}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}