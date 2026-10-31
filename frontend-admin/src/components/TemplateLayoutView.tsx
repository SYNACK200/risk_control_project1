import { useEffect, useState } from 'react';

import { getTemplateLayout, getTemplateLayoutPng, type TemplateLayoutPayload } from '../lib/api';

const FIELD_LABEL: Record<string, string> = {
  txn_date: '交易日期', summary: '摘要', amount: '金额', balance: '余额',
  currency: '币种', account_no: '账号', channel: '渠道', direction: '收支方向',
  counterparty: '对方户名', memo: '备注',
};

const PALETTE = ['#e64a3d', '#2a78d9', '#1f9e5c', '#d98a19', '#8c4ccd', '#189aa6', '#bf3f8c', '#737313'];

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

  if (!data.has_sample || !data.layout) {
    return (
      <div className="layout-empty">
        <div className="muted">该模板建于「保存样本」功能之前，只记录了列序号，无法回看当时的框选。</div>
        <div className="muted small">处理办法：到「模板标注」里用同一份流水重新标注一次并保存为新版本，之后即可回看。</div>
      </div>
    );
  }

  const boxes = data.layout.boxes ?? [];
  const pages = data.layout.pages ?? {};
  const pageKeys = Object.keys(pages).map(Number).sort((a, b) => a - b);
  const seen = new Map<string, number>();
  boxes.forEach((b, i) => { if (!seen.has(b.field)) seen.set(b.field, i); });

  return (
    <div className="layout-view">
      <div className="layout-head">
        <strong>当时的框选</strong>
        <span className="muted small">共 {boxes.length} 个字段 · 样本页 {pageKeys.length} 页</span>
        {pageKeys.length > 1 && (
          <span className="layout-pager">
            {pageKeys.map(n => (
              <button key={n} type="button" className={'pill-btn' + (n === page ? ' pill-btn-primary' : '')}
                onClick={() => setPage(n)}>第 {n + 1} 页</button>
            ))}
          </span>
        )}
      </div>
      <div className="layout-body">
        <div className="layout-image">
          {url ? <img src={url} alt={'模板 ' + templateId + ' 第 ' + (page + 1) + ' 页框选'} /> : <div className="muted small">正在渲染样本页…</div>}
        </div>
        <ul className="layout-legend">
          {[...seen.entries()].map(([field, index]) => {
            const box = boxes[index];
            return (
              <li key={field}>
                <span className="legend-dot" style={{ background: PALETTE[index % PALETTE.length] }} />
                <span className="legend-field">{FIELD_LABEL[field] ?? field}</span>
                <span className="muted small">{box.column || '—'}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
