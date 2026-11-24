import { useEffect, useRef, useState } from 'react';
import { PdfPageCanvas, type PageRenderSize } from '../PdfPageCanvas';
import {
  BOX_COLORS,
  fieldLabel,
  type ColumnBox,
  type CustomFieldOption,
  type SingleBox,
  type TableRegionBox,
  type ToolMode,
} from './types';

type Props = {
  fileBytes: ArrayBuffer | null;
  mimeHint?: string;
  pageIndex: number;
  zoom: number;
  password?: string;
  tool: ToolMode;
  showBoxes: boolean;
  regions: TableRegionBox[];
  columns: ColumnBox[];
  singles: SingleBox[];
  customFields: CustomFieldOption[];
  activeRegionId: string | null;
  selected: { kind: 'region' | 'col' | 'single'; id: string } | null;
  onSelect: (sel: { kind: 'region' | 'col' | 'single'; id: string } | null) => void;
  onSelectRegion: (regionId: string) => void;
  onUpdateRegion: (id: string, patch: Partial<TableRegionBox>) => void;
  onCreateRegion: (area: { x: number; y: number; w: number; h: number }) => void;
  onUpdateColumn: (id: string, patch: Partial<ColumnBox>) => void;
  onCreateColumn: (box: { x: number; w: number; regionId?: string }) => void;
  onUpdateSingle: (id: string, patch: Partial<SingleBox>) => void;
  onCreateSingle: (rect: { x: number; y: number; w: number; h: number }) => void;
  onCommitHistory: () => void;
  onPageInfo?: (info: PageRenderSize) => void;
  onPasswordRequired?: () => void;
  onError?: (msg: string) => void;
  onSpreadAt?: (nx: number, ny: number) => void;
};

type DragState =
  | { kind: 'col'; id: string; mode: 'move' | 'left' | 'right'; startX: number; origX: number; origW: number; committed?: boolean }
  | {
      kind: 'area';
      id: string;
      mode: 'move' | 'nw' | 'ne' | 'sw' | 'se';
      startX: number;
      startY: number;
      orig: { x: number; y: number; w: number; h: number };
      committed?: boolean;
    }
  | { kind: 'header_y'; id: string; startY: number; origHeaderY: number; committed?: boolean }
  | {
      kind: 'single';
      id: string;
      mode: 'move' | 'right' | 'bottom' | 'corner';
      startX: number;
      startY: number;
      orig: { x: number; y: number; w: number; h: number };
      committed?: boolean;
    }
  | { kind: 'draw'; mode: 'draw_col' | 'draw_area' | 'draw_single'; x0: number; y0: number; x1: number; y1: number };

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

export function CanvasStage({
  fileBytes,
  mimeHint,
  pageIndex,
  zoom,
  password,
  tool,
  showBoxes,
  regions,
  columns,
  singles,
  customFields,
  activeRegionId,
  selected,
  onSelect,
  onSelectRegion,
  onUpdateRegion,
  onCreateRegion,
  onUpdateColumn,
  onCreateColumn,
  onUpdateSingle,
  onCreateSingle,
  onCommitHistory,
  onPageInfo,
  onPasswordRequired,
  onError,
  onSpreadAt,
}: Props) {
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const [renderSize, setRenderSize] = useState<PageRenderSize | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const [rubber, setRubber] = useState<{ x: number; y: number; w: number; h: number } | null>(null);

  const pageRegions = regions.filter((r) => r.page === pageIndex);
  const activeRegion =
    pageRegions.find((r) => r.id === activeRegionId) ?? pageRegions[0] ?? regions[0] ?? null;
  const regionMap = new Map(pageRegions.map((r) => [r.id, r]));
  const pageColumns = columns.filter((c) => regionMap.has(c.regionId));
  const pageSingles = singles.filter((s) => s.page === pageIndex);

  const clientToNorm = (clientX: number, clientY: number) => {
    const el = overlayRef.current;
    if (!el) return { nx: 0, ny: 0 };
    const rect = el.getBoundingClientRect();
    const nx = rect.width > 0 ? clamp((clientX - rect.left) / rect.width, 0, 1) : 0;
    const ny = rect.height > 0 ? clamp((clientY - rect.top) / rect.height, 0, 1) : 0;
    return { nx, ny };
  };

  const callbacksRef = useRef({
    activeRegion,
    onUpdateColumn,
    onUpdateRegion,
    onUpdateSingle,
    onCreateColumn,
    onCreateRegion,
    onCreateSingle,
    onCommitHistory,
  });
  callbacksRef.current = {
    activeRegion,
    onUpdateColumn,
    onUpdateRegion,
    onUpdateSingle,
    onCreateColumn,
    onCreateRegion,
    onCreateSingle,
    onCommitHistory,
  };

  useEffect(() => {
    const ensureCommitted = (st: Exclude<DragState, { kind: 'draw' }>) => {
      if (!st.committed) {
        st.committed = true;
        callbacksRef.current.onCommitHistory();
      }
    };

    const onMove = (e: PointerEvent) => {
      const st = dragRef.current;
      if (!st) return;
      const { nx, ny } = clientToNorm(e.clientX, e.clientY);
      const cb = callbacksRef.current;

      if (st.kind === 'col') {
        const dx = nx - st.startX;
        if (dx === 0) return;
        ensureCommitted(st);
        if (st.mode === 'move') {
          cb.onUpdateColumn(st.id, { x: clamp(st.origX + dx, 0, 1 - st.origW) });
        } else if (st.mode === 'left') {
          const right = st.origX + st.origW;
          const nextX = clamp(st.origX + dx, 0, right - 0.012);
          cb.onUpdateColumn(st.id, { x: nextX, w: right - nextX });
        } else {
          const nextW = clamp(st.origW + dx, 0.012, 1 - st.origX);
          cb.onUpdateColumn(st.id, { w: nextW });
        }
      } else if (st.kind === 'area') {
        const dx = nx - st.startX;
        const dy = ny - st.startY;
        if (dx === 0 && dy === 0) return;
        ensureCommitted(st);
        const o = st.orig;
        if (st.mode === 'move') {
          cb.onUpdateRegion(st.id, {
            area: { x: clamp(o.x + dx, 0, 1 - o.w), y: clamp(o.y + dy, 0, 1 - o.h), w: o.w, h: o.h },
          });
        } else {
          let x0 = o.x;
          let y0 = o.y;
          let x1 = o.x + o.w;
          let y1 = o.y + o.h;
          if (st.mode === 'nw' || st.mode === 'sw') x0 = clamp(o.x + dx, 0, x1 - 0.06);
          if (st.mode === 'ne' || st.mode === 'se') x1 = clamp(o.x + o.w + dx, x0 + 0.06, 1);
          if (st.mode === 'nw' || st.mode === 'ne') y0 = clamp(o.y + dy, 0, y1 - 0.05);
          if (st.mode === 'sw' || st.mode === 'se') y1 = clamp(o.y + o.h + dy, y0 + 0.05, 1);
          cb.onUpdateRegion(st.id, { area: { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } });
        }
      } else if (st.kind === 'header_y') {
        const dy = ny - st.startY;
        if (dy === 0) return;
        ensureCommitted(st);
        cb.onUpdateRegion(st.id, { headerY: clamp(st.origHeaderY + dy, 0, 1) });
      } else if (st.kind === 'single') {
        const dx = nx - st.startX;
        const dy = ny - st.startY;
        if (dx === 0 && dy === 0) return;
        ensureCommitted(st);
        const o = st.orig;
        if (st.mode === 'move') {
          cb.onUpdateSingle(st.id, { x: clamp(o.x + dx, 0, 1 - o.w), y: clamp(o.y + dy, 0, 1 - o.h), manual: true });
        } else {
          cb.onUpdateSingle(st.id, {
            w: st.mode === 'right' || st.mode === 'corner' ? clamp(o.w + dx, 0.02, 1 - o.x) : o.w,
            h: st.mode === 'bottom' || st.mode === 'corner' ? clamp(o.h + dy, 0.012, 1 - o.y) : o.h,
            manual: true,
          });
        }
      } else if (st.kind === 'draw') {
        st.x1 = nx;
        st.y1 = ny;
        setRubber({
          x: Math.min(st.x0, nx),
          y: Math.min(st.y0, ny),
          w: Math.abs(nx - st.x0),
          h: Math.abs(ny - st.y0),
        });
      }
    };

    const onUp = () => {
      const st = dragRef.current;
      if (!st) return;
      dragRef.current = null;
      setRubber(null);
      const cb = callbacksRef.current;

      if (st.kind === 'draw') {
        const x = Math.min(st.x0, st.x1);
        const y = Math.min(st.y0, st.y1);
        const w = Math.abs(st.x1 - st.x0);
        const h = Math.abs(st.y1 - st.y0);
        if (w < 0.012) return;
        if (st.mode === 'draw_col') {
          cb.onCommitHistory();
          cb.onCreateColumn({ x, w, regionId: cb.activeRegion?.id });
        } else if (st.mode === 'draw_area') {
          if (h < 0.03) return;
          cb.onCommitHistory();
          cb.onCreateRegion({ x, y, w, h });
        } else if (st.mode === 'draw_single') {
          if (h < 0.01) return;
          cb.onCommitHistory();
          cb.onCreateSingle({ x, y, w, h });
        }
      }
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, []);

  const handleStagePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!renderSize) return;
    const { nx, ny } = clientToNorm(e.clientX, e.clientY);
    if (tool === 'draw_col' || tool === 'draw_area' || tool === 'draw_single') {
      e.preventDefault();
      dragRef.current = { kind: 'draw', mode: tool, x0: nx, y0: ny, x1: nx, y1: ny };
      setRubber({ x: nx, y: ny, w: 0, h: 0 });
      return;
    }
    if (tool === 'header_line' && activeRegion) {
      e.preventDefault();
      onCommitHistory();
      onUpdateRegion(activeRegion.id, { headerY: ny });
      return;
    }
    if (tool === 'spread') {
      e.preventDefault();
      onSpreadAt?.(nx, ny);
      return;
    }
    onSelect(null);
  };

  const cursorClass =
    tool === 'draw_col' || tool === 'draw_area' || tool === 'draw_single'
      ? 'cursor-crosshair'
      : tool === 'header_line'
        ? 'cursor-row-resize'
        : tool === 'spread'
          ? 'cursor-cell'
          : '';

  return (
    <div style={{ width: '100%' }}>
      <div className="ann-legend" style={{ display: 'flex', flexWrap: 'wrap', gap: 12, padding: '6px 10px', fontSize: 12, color: '#4b5563', borderBottom: '1px solid #e5e7eb', background: '#f9fafb' }}>
        <span><i style={{ display: 'inline-block', width: 10, height: 10, border: '2px dashed #7c3aed', marginRight: 4, verticalAlign: 'middle' }} />紫色虚线：表格区</span>
        <span><i style={{ display: 'inline-block', width: 10, height: 2, background: '#d97706', marginRight: 4, verticalAlign: 'middle' }} />琥珀横线：表头基准线（线上不计交易）</span>
        <span><i style={{ display: 'inline-block', width: 10, height: 10, background: '#2563eb22', border: '1.5px solid #2563eb', marginRight: 4, verticalAlign: 'middle' }} />彩色竖框：交易列带</span>
        <span><i style={{ display: 'inline-block', width: 10, height: 10, border: '1.5px dashed #0f766e', marginRight: 4, verticalAlign: 'middle' }} />青色虚框：页眉单值字段</span>
      </div>
      <PdfPageCanvas
      fileBytes={fileBytes}
      mimeHint={mimeHint}
      pageIndex={pageIndex}
      zoom={zoom}
      password={password}
      onPasswordRequired={onPasswordRequired}
      onError={onError}
      onPageInfo={(info) => {
        setRenderSize(info);
        onPageInfo?.(info);
      }}
    >
      {(size) => (
        <div
          ref={overlayRef}
          className={`ann-overlay ${cursorClass}`}
          onPointerDown={handleStagePointerDown}
        >
          {size && showBoxes && (
            <>
              {/* 1. 表格区（紫色虚线框）与表头线（琥珀横线） */}
              {pageRegions.map((reg, rIdx) => {
                const isActiveReg = activeRegion?.id === reg.id;
                const isSel = selected?.kind === 'region' && selected.id === reg.id;
                const dimmed = selected && selected.kind === 'single';
                return (
                  <div key={reg.id}>
                    <div
                      className={`ann-area-box ${isActiveReg ? 'active' : ''} ${isSel ? 'selected' : ''} ${dimmed ? 'dim' : ''}`}
                      style={{
                        left: `${reg.area.x * 100}%`,
                        top: `${reg.area.y * 100}%`,
                        width: `${reg.area.w * 100}%`,
                        height: `${reg.area.h * 100}%`,
                      }}
                      onPointerDown={(e) => {
                        if (tool !== 'select') return;
                        e.stopPropagation();
                        onSelectRegion(reg.id);
                        onSelect({ kind: 'region', id: reg.id });
                        const { nx, ny } = clientToNorm(e.clientX, e.clientY);
                        dragRef.current = {
                          kind: 'area',
                          id: reg.id,
                          mode: 'move',
                          startX: nx,
                          startY: ny,
                          orig: { ...reg.area },
                        };
                      }}
                    >
                      <span className="ann-area-tag">
                        表格区{pageRegions.length > 1 ? ` ${rIdx + 1}` : ''} ({reg.slot})
                      </span>
                      {(['nw', 'ne', 'sw', 'se'] as const).map((corner) => (
                        <span
                          key={corner}
                          className={`ann-corner ${corner}`}
                          onPointerDown={(e) => {
                            if (tool !== 'select') return;
                            e.stopPropagation();
                            onSelectRegion(reg.id);
                            onSelect({ kind: 'region', id: reg.id });
                            const { nx, ny } = clientToNorm(e.clientX, e.clientY);
                            dragRef.current = {
                              kind: 'area',
                              id: reg.id,
                              mode: corner,
                              startX: nx,
                              startY: ny,
                              orig: { ...reg.area },
                            };
                          }}
                        />
                      ))}
                    </div>

                    {/* 表头基准线 */}
                    <div
                      className="ann-header-line"
                      style={{
                        left: `${reg.area.x * 100}%`,
                        width: `${reg.area.w * 100}%`,
                        top: `${reg.headerY * 100}%`,
                      }}
                      title="拖动可调整表头位置（表头之上的文字不会被当成交易行）"
                      onPointerDown={(e) => {
                        if (tool !== 'select' && tool !== 'header_line') return;
                        e.stopPropagation();
                        onSelectRegion(reg.id);
                        const { ny } = clientToNorm(e.clientX, e.clientY);
                        dragRef.current = {
                          kind: 'header_y',
                          id: reg.id,
                          startY: ny,
                          origHeaderY: reg.headerY,
                        };
                      }}
                    >
                      <span className="ann-header-pill">表头线</span>
                    </div>
                  </div>
                );
              })}

              {/* 2. 列带（严格限定在所属表格区高度范围内，不遮挡顶部信息与页脚） */}
              {pageColumns.map((col, idx) => {
                const reg = regionMap.get(col.regionId);
                if (!reg) return null;
                const color = BOX_COLORS[idx % BOX_COLORS.length];
                const isSel = selected?.kind === 'col' && selected.id === col.id;
                const dimmed = selected && selected.id !== col.id;
                const label = fieldLabel(col.field, customFields);
                // 列带从表头基准线下方起算（避免遮挡表头行），并保证至少 3% 最小可视宽度
                const areaBottom = reg.area.y + reg.area.h;
                const colTop = reg.headerY > reg.area.y && reg.headerY < areaBottom - 0.01 ? reg.headerY : reg.area.y;
                const colHeight = Math.max(0.02, areaBottom - colTop);
                // 显示宽度取「列宽 ∪ 实际读到格子的包络」：模板/预读给的宽度常常只覆盖表头词
                // （「交易时间」4 个字），而值是「2026-10-01」更长——不扩就会看着框偏左。
                // 只影响显示，保存的仍是 col.x / col.w。
                const cellsX = (col.cellNorms ?? []).flatMap((c) => [c.x0, c.x1]);
                const boxLeft = cellsX.length ? Math.min(col.x, ...cellsX) : col.x;
                const boxRight = cellsX.length ? Math.max(col.x + col.w, ...cellsX) : col.x + col.w;
                const displayX = Math.max(0, boxLeft);
                const displayW = Math.min(1 - displayX, Math.max(boxRight - displayX, 0.03));

                return (
                  <div key={col.id}>
                    {isSel &&
                      col.cellNorms?.map((c, cIdx) => (
                        <div
                          key={cIdx}
                          className="ann-cell-dot"
                          style={{
                            left: `${c.x0 * 100}%`,
                            top: `${c.y0 * 100}%`,
                            width: `${Math.max(0.008, c.x1 - c.x0) * 100}%`,
                            height: `${Math.max(0.008, c.y1 - c.y0) * 100}%`,
                            borderColor: color,
                          }}
                        />
                      ))}
                    <div
                      className={`ann-col-box ${isSel ? 'selected' : ''} ${dimmed ? 'dim' : ''}`}
                      style={{
                        // 框向外扩 2px：边框直接压在被框的字上时，首尾字符会被盖掉半个，
                        // 看起来像「框圈歪了」。外扩后框住范围不变，但不再遮挡内容。
                        left: `calc(${displayX * 100}% - 2px)`,
                        top: `calc(${colTop * 100}% - 2px)`,
                        width: `calc(${displayW * 100}% + 4px)`,
                        height: `calc(${colHeight * 100}% + 4px)`,
                        borderColor: color,
                        backgroundColor: isSel ? `${color}22` : `${color}12`,
                      }}
                      onPointerDown={(e) => {
                        if (tool !== 'select') return;
                        e.stopPropagation();
                        onSelectRegion(col.regionId);
                        onSelect({ kind: 'col', id: col.id });
                        const { nx } = clientToNorm(e.clientX, e.clientY);
                        dragRef.current = {
                          kind: 'col',
                          id: col.id,
                          mode: 'move',
                          startX: nx,
                          origX: col.x,
                          origW: col.w,
                        };
                      }}
                    >
                      <span
                        className="ann-col-edge left"
                        style={{ background: color }}
                        onPointerDown={(e) => {
                          if (tool !== 'select') return;
                          e.stopPropagation();
                          onSelect({ kind: 'col', id: col.id });
                          const { nx } = clientToNorm(e.clientX, e.clientY);
                          dragRef.current = {
                            kind: 'col',
                            id: col.id,
                            mode: 'left',
                            startX: nx,
                            origX: col.x,
                            origW: col.w,
                          };
                        }}
                      />
                      <span
                        className="ann-col-edge right"
                        style={{ background: color }}
                        onPointerDown={(e) => {
                          if (tool !== 'select') return;
                          e.stopPropagation();
                          onSelect({ kind: 'col', id: col.id });
                          const { nx } = clientToNorm(e.clientX, e.clientY);
                          dragRef.current = {
                            kind: 'col',
                            id: col.id,
                            mode: 'right',
                            startX: nx,
                            origX: col.x,
                            origW: col.w,
                          };
                        }}
                      />
                      <span className="ann-col-tag" style={{ background: color }}>
                        {label}
                        {col.cells.length > 0 && <em>{col.cells.length}</em>}
                      </span>
                    </div>
                  </div>
                );
              })}

              {/* 3. 页内单值框（卡号/户名/开户行/账户类型） */}
              {pageSingles.map((s) => {
                const isSel = selected?.kind === 'single' && selected.id === s.id;
                const dimmed = selected && selected.id !== s.id;
                return (
                  <div
                    key={s.id}
                    className={`ann-single-box ${isSel ? 'selected' : ''} ${dimmed ? 'dim' : ''}`}
                    style={{
                      // 同列带：外扩 2px，避免边框压住卡号首尾字符
                      left: `calc(${s.x * 100}% - 2px)`,
                      top: `calc(${s.y * 100}% - 2px)`,
                      width: `calc(${s.w * 100}% + 4px)`,
                      height: `calc(${s.h * 100}% + 4px)`,
                    }}
                    onPointerDown={(e) => {
                      if (tool !== 'select') return;
                      e.stopPropagation();
                      onSelect({ kind: 'single', id: s.id });
                      const { nx, ny } = clientToNorm(e.clientX, e.clientY);
                      dragRef.current = {
                        kind: 'single',
                        id: s.id,
                        mode: 'move',
                        startX: nx,
                        startY: ny,
                        orig: { x: s.x, y: s.y, w: s.w, h: s.h },
                      };
                    }}
                  >
                    <span className="ann-single-tag">
                      {s.label}
                      {s.value ? `：${s.value.slice(0, 14)}` : ''}
                    </span>
                    <span
                      className="ann-single-handle right"
                      onPointerDown={(e) => {
                        if (tool !== 'select') return;
                        e.stopPropagation();
                        onSelect({ kind: 'single', id: s.id });
                        const { nx, ny } = clientToNorm(e.clientX, e.clientY);
                        dragRef.current = {
                          kind: 'single',
                          id: s.id,
                          mode: 'right',
                          startX: nx,
                          startY: ny,
                          orig: { x: s.x, y: s.y, w: s.w, h: s.h },
                        };
                      }}
                    />
                    <span
                      className="ann-single-handle bottom"
                      onPointerDown={(e) => {
                        if (tool !== 'select') return;
                        e.stopPropagation();
                        onSelect({ kind: 'single', id: s.id });
                        const { nx, ny } = clientToNorm(e.clientX, e.clientY);
                        dragRef.current = {
                          kind: 'single',
                          id: s.id,
                          mode: 'bottom',
                          startX: nx,
                          startY: ny,
                          orig: { x: s.x, y: s.y, w: s.w, h: s.h },
                        };
                      }}
                    />
                    <span
                      className="ann-single-handle corner"
                      onPointerDown={(e) => {
                        if (tool !== 'select') return;
                        e.stopPropagation();
                        onSelect({ kind: 'single', id: s.id });
                        const { nx, ny } = clientToNorm(e.clientX, e.clientY);
                        dragRef.current = {
                          kind: 'single',
                          id: s.id,
                          mode: 'corner',
                          startX: nx,
                          startY: ny,
                          orig: { x: s.x, y: s.y, w: s.w, h: s.h },
                        };
                      }}
                    />
                  </div>
                );
              })}
            </>
          )}

          {/* 手动拖拽框选的橡皮筋反馈 */}
          {rubber && (
            <div
              className="ann-rubber"
              style={{
                left: `${rubber.x * 100}%`,
                top: `${rubber.y * 100}%`,
                width: `${rubber.w * 100}%`,
                height: `${rubber.h * 100}%`,
              }}
            />
          )}
        </div>
      )}
      </PdfPageCanvas>
    </div>
  );
}
