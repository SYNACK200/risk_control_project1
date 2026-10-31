import { Fragment, useState } from 'react';
import type { ReportCheck } from '../lib/api';

interface Props {
  items: ReportCheck[];
  methods: Record<string, string>;
}

const STATUS_LABEL: Record<string, string> = {
  pass: '通过',
  partial: '部分',
  skipped: '未执行',
  fail: '不通过',
  inconsistent: '不一致',
  limited: '受限',
  unavailable: '不可用',
};

export function CheckTable({ items, methods }: Props) {
  const [open, setOpen] = useState<string | null>(null);
  if (items.length === 0) return <p className="muted">本层没有可展示的检查点。</p>;
  return (
    <table className="mini check-table">
      <thead><tr><th></th><th>编码</th><th>检查点</th><th>当前结果</th><th>结论说明</th></tr></thead>
      <tbody>
        {items.map(item => (
          <Fragment key={item.code}>
            <tr className={'check-row' + (open === item.code ? ' open' : '')} onClick={() => setOpen(open === item.code ? null : item.code)}>
              <td className="caret">{open === item.code ? '▾' : '▸'}</td>
              <td className="mono">{item.code}</td>
              <td>{item.name}</td>
              <td><span className={'check-status ' + item.status}>{STATUS_LABEL[item.status] ?? item.status}</span></td>
              <td className="muted">{item.detail || '—'}</td>
            </tr>
            {open === item.code && (
              <tr className="check-detail-row">
                <td />
                <td colSpan={4}>
                  <div className="check-explain">
                    <div><span className="me-k">怎么验</span><span className="me-v">{methods[item.code] || '（方法说明未加载）'}</span></div>
                    <div><span className="me-k">本次结论</span><span className="me-v">{item.detail || '无补充说明'}</span></div>
                    <div><span className="me-k">状态含义</span><span className="me-v">通过＝已验且一致；部分/受限＝只验了一部分；未执行＝缺必要输入；不通过＝验出矛盾，需人工复核</span></div>
                  </div>
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}
