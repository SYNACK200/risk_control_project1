import type { PageSlot, ToolMode } from './types';

type Props = {
  tool: ToolMode;
  onToolChange: (mode: ToolMode) => void;
  pageIndex: number;
  pageCount: number;
  onPageChange: (index: number) => void;
  currentSlot?: PageSlot;
  onSlotChange?: (slot: PageSlot) => void;
  zoom: number;
  onZoomChange: (zoom: number) => void;
  showBoxes: boolean;
  onToggleBoxes: () => void;
  focusWork: boolean;
  onToggleFocus: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  ocrUsed?: boolean;
  onReOcrPage?: () => void;
  busy?: boolean;
};

const TOOLS: { mode: ToolMode; label: string; tip: string }[] = [
  { mode: 'select', label: '选择 / 拖拽', tip: '拖动或拉宽已有的列框、表格区和单值框' },
  { mode: 'draw_col', label: '+ 框选列', tip: '按住鼠标在表格列上拖出一个新的列框' },
  { mode: 'draw_area', label: '+ 框选表格区', tip: '按住鼠标圈出表格有效范围（同页多表可圈多个）' },
  { mode: 'draw_single', label: '+ 框选单值', tip: '按住鼠标圈出卡号、户名、开户行等页内单值' },
  { mode: 'header_line', label: '设表头线', tip: '点击表头所在高度，防止表头被当成数据' },
  { mode: 'spread', label: '点词识别', tip: '输入关键字（如 卡号/摘要）自动向下找同列数据' },
];

export function AnnotateToolbar({
  tool,
  onToolChange,
  pageIndex,
  pageCount,
  onPageChange,
  currentSlot,
  onSlotChange,
  zoom,
  onZoomChange,
  showBoxes,
  onToggleBoxes,
  focusWork,
  onToggleFocus,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  ocrUsed,
  onReOcrPage,
  busy,
}: Props) {
  return (
    <div className="ann-toolbar">
      <div className="ann-toolbar-group" role="group" aria-label="标注工具">
        {TOOLS.map((t) => (
          <button
            key={t.mode}
            type="button"
            title={t.tip}
            className={tool === t.mode ? 'ann-tool active' : 'ann-tool'}
            onClick={() => onToolChange(t.mode)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="ann-toolbar-group">
        <button
          type="button"
          className="ann-btn"
          disabled={!canUndo}
          title="撤销 (Ctrl+Z)"
          onClick={onUndo}
        >
          撤销
        </button>
        <button
          type="button"
          className="ann-btn"
          disabled={!canRedo}
          title="重做 (Ctrl+Y)"
          onClick={onRedo}
        >
          重做
        </button>
        <button type="button" className="ann-btn" onClick={onToggleBoxes}>
          {showBoxes ? '隐藏框' : '显示框'}
        </button>
      </div>

      <div className="ann-toolbar-group">
        {pageCount > 1 && (
          <>
            <button
              type="button"
              className="ann-btn"
              disabled={pageIndex <= 0}
              onClick={() => onPageChange(pageIndex - 1)}
            >
              ‹
            </button>
            <span className="ann-page-num">
              第 {pageIndex + 1}/{pageCount} 页
            </span>
            <button
              type="button"
              className="ann-btn"
              disabled={pageIndex >= pageCount - 1}
              onClick={() => onPageChange(pageIndex + 1)}
            >
              ›
            </button>
          </>
        )}
        {currentSlot && onSlotChange && (
          <select
            className="ann-slot-select"
            title="这页表格在整份流水里的角色"
            value={currentSlot}
            onChange={(e) => onSlotChange(e.target.value as PageSlot)}
          >
            <option value="first">首页版式 (first)</option>
            <option value="middle">续页版式 (middle)</option>
            <option value="last">末页版式 (last)</option>
            <option value="auto">全部页通用 (auto)</option>
          </select>
        )}
        {ocrUsed && onReOcrPage && (
          <button
            type="button"
            className="ann-btn"
            disabled={busy}
            title="对当前页重新跑 OCR 识字并自动识别列"
            onClick={onReOcrPage}
          >
            OCR 识别本页
          </button>
        )}
      </div>

      <div className="ann-toolbar-group">
        <button
          type="button"
          className="ann-btn"
          onClick={() => onZoomChange(Math.max(0.6, Number((zoom - 0.15).toFixed(2))))}
        >
          −
        </button>
        <span className="ann-zoom-num">{Math.round(zoom * 100)}%</span>
        <button
          type="button"
          className="ann-btn"
          onClick={() => onZoomChange(Math.min(2.4, Number((zoom + 0.15).toFixed(2))))}
        >
          ＋
        </button>
        <button type="button" className="ann-btn" onClick={() => onZoomChange(1.15)}>
          适应
        </button>
        <button type="button" className="ann-btn" onClick={onToggleFocus}>
          {focusWork ? '退出专注' : '专注画布'}
        </button>
      </div>
    </div>
  );
}
