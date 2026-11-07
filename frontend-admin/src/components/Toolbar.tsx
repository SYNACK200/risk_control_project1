import type { Tool } from '../lib/types';

interface Props {
  tool: Tool;
  onTool: (t: Tool) => void;
  page: number;
  pageCount: number;
  onPage: (p: number) => void;
  zoom: number;
  onZoom: (z: number) => void;
  onFile: (f: File) => void;
  onDemo: () => void;
  onSave: () => void;
  onReset: () => void;
  blocking: number;
}

export function Toolbar(p: Props) {
  return (
    <div className="toolbar">
      <div className="group">
        <label className="btn" style={{ padding: '6px 12px', border: '1px solid #cbd5e1', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>
          载入样例
          <input
            type="file"
            accept=".pdf,.jpg,.jpeg,.png"
            style={{ display: 'none' }}
            onChange={e => {
              const f = e.target.files?.[0];
              if (f) p.onFile(f);
              e.target.value = '';
            }}
          />
        </label>
        <button className="btn" onClick={p.onDemo}>示例页</button>
      </div>

      <div className="group">
        {/* 选择模式：不画东西，只用来点中对象、拖动、拖手柄改大小 */}
        <button className={`btn ${p.tool === 'select' ? 'tool-active' : ''}`} onClick={() => p.onTool('select')}
          title="选中对象后可以拖动位置、拖八个手柄改大小">
          选择 / 调整
        </button>
        <button className={`btn ${p.tool === 'meta' ? 'tool-active' : ''}`} onClick={() => p.onTool('meta')}>
          画字段框
        </button>
        <button className={`btn ${p.tool === 'table' ? 'tool-active' : ''}`} onClick={() => p.onTool('table')}>
          画表格区
        </button>
        <button className={`btn ${p.tool === 'column' ? 'tool-active' : ''}`} onClick={() => p.onTool('column')}>
          画列边界
        </button>
      </div>

      <div className="group">
        <button className="btn" disabled={p.page <= 1} onClick={() => p.onPage(p.page - 1)}>上一页</button>
        <span className="muted">{p.pageCount > 0 ? `${p.page} / ${p.pageCount}` : '— / —'}</span>
        <button className="btn" disabled={p.page >= p.pageCount} onClick={() => p.onPage(p.page + 1)}>下一页</button>
      </div>

      <div className="group zoom-group">
        {/* 连续缩放：三档按钮不够用，长表格和小字都要能调到合适的比例 */}
        <button className="btn zoom-step" type="button" title="缩小"
          onClick={() => p.onZoom(Math.max(0.2, Math.round((p.zoom - 0.05) * 100) / 100))}>−</button>
        <input
          className="zoom-range"
          type="range"
          min={20}
          max={400}
          step={5}
          value={Math.round(p.zoom * 100)}
          onChange={e => p.onZoom(Number(e.target.value) / 100)}
          title="拖动调整缩放（20%–400%，每格 5%）"
        />
        <button className="btn zoom-step" type="button" title="放大"
          onClick={() => p.onZoom(Math.min(4, Math.round((p.zoom + 0.05) * 100) / 100))}>＋</button>
        <span className="muted small zoom-value">{Math.round(p.zoom * 100)}%</span>
        <button className="btn zoom-reset" type="button" onClick={() => p.onZoom(1)}>100%</button>
      </div>

      <div className="group">
        <button className="btn primary" onClick={p.onSave}>
          {p.blocking > 0 ? `保存（${p.blocking} 项待修）` : '保存并导出'}
        </button>
        <button className="btn danger" onClick={p.onReset}>清空</button>
      </div>
    </div>
  );
}