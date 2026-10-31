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
  onHint: (text: string) => void;
}

type Drag =
  | { mode: 'create'; start: { x: number; y: number }; rect: Rect }
  | { mode: 'move'; kind: 'meta' | 'table'; id: string; start: { x: number; y: number }; origin: Rect }
  | { mode: 'resize'; kind: 'meta' | 'table'; id: string; origin: Rect }
  | null;

export function Stage(p: Props) {
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
    if (drag.mode === 'resize') {
      const rect = rectFromPoints(
        drag.origin.x, drag.origin.y,
        Math.max(drag.origin.x + 0.002, now.x),
        Math.max(drag.origin.y + 0.002, now.y),
      );
      p.onMove(drag.kind, drag.id, rect);
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
        <div className="page-holder" ref={holderRef}>
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
                    ev.stopPropagation();
                    p.onSelect({ kind: 'table', id: t.id });
                    const start = toRel(ev);
                    setDrag({ mode: 'move', kind: 'table', id: t.id, start, origin: t.area });
                    ev.currentTarget.setPointerCapture(ev.pointerId);
                  }}
                >
                  <span className="box-label">表格区 · {t.columns.length} 列</span>
                  {selected && (
                    <span
                      className="handle"
                      onPointerDown={ev => {
                        ev.stopPropagation();
                        setDrag({ mode: 'resize', kind: 'table', id: t.id, origin: t.area });
                        ev.currentTarget.setPointerCapture(ev.pointerId);
                      }}
                    />
                  )}
                  {t.columns.map((col, idx) => {
                    const colSel = p.sel?.kind === 'column' && p.sel.tableId === t.id && p.sel.index === idx;
                    return (
                      <div
                        key={`${t.id}-c${idx}`}
                        className={`box column ${colSel ? 'selected' : ''} ${col.field ? '' : 'unassigned'}`}
                        style={{ left: `${(col.x - t.area.x) / t.area.w * 100}%`, top: 0, width: `${col.w / t.area.w * 100}%`, height: '100%' }}
                        onPointerDown={ev => {
                          ev.stopPropagation();
                          p.onSelect({ kind: 'column', tableId: t.id, index: idx });
                        }}
                      >
                        <span className="box-label">{col.field ? labelOf(col.field, p.map.custom_fields) : '未指定'}</span>
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
                    ev.currentTarget.setPointerCapture(ev.pointerId);
                  }}
                >
                  <span className="box-label">{b.field ? labelOf(b.field, p.map.custom_fields) : '未指定字段'}</span>
                  {selected && (
                    <span
                      className="handle"
                      onPointerDown={ev => {
                        ev.stopPropagation();
                        setDrag({ mode: 'resize', kind: 'meta', id: b.id, origin: b.rect });
                        ev.currentTarget.setPointerCapture(ev.pointerId);
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
