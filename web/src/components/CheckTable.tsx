import { Fragment, useState } from 'react';

export interface LayerCheckItem {
  code?: string;
  name?: string;
  method?: string;
  status?: string;
  detail?: string;
}

const STATUS_LABEL: Record<string, { label: string; cls: string }> = {
  pass: { label: '通过', cls: 'pill ok' },
  partial: { label: '部分', cls: 'pill warn' },
  skipped: { label: '未执行', cls: 'pill' },
  fail: { label: '不通过', cls: 'pill err' },
  inconsistent: { label: '不一致', cls: 'pill err' },
  limited: { label: '受限', cls: 'pill warn' },
  warn: { label: '告警', cls: 'pill warn' },
  unavailable: { label: '不可用', cls: 'pill' },
};

/** 可展开查看「怎么验」方法说明的四层核验明细表。 */
export function CheckTable({
  items,
  methods,
}: {
  items: LayerCheckItem[];
  methods: Record<string, string>;
}) {
  const [open, setOpen] = useState<string | null>(null);
  if (items.length === 0) return <p className="muted small">本层没有可展示的检查点。</p>;

  return (
    <table className="grid compact check-table">
      <thead>
        <tr>
          <th style={{ width: 28 }} />
          <th>编码</th>
          <th>检查点</th>
          <th>当前结果</th>
          <th>结论说明</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item, idx) => {
          const code = item.code || String(idx);
          const isOpen = open === code;
          const badge = STATUS_LABEL[item.status ?? ''] ?? { label: item.status || '—', cls: 'pill' };
          return (
            <Fragment key={code}>
              <tr
                className={'check-row' + (isOpen ? ' open' : '')}
                style={{ cursor: 'pointer' }}
                onClick={() => setOpen(isOpen ? null : code)}
              >
                <td className="caret">{isOpen ? '▾' : '▸'}</td>
                <td className="mono small">{item.code || '—'}</td>
                <td>{item.name || item.method || '—'}</td>
                <td><span className={badge.cls}>{badge.label}</span></td>
                <td className="small muted">{item.detail || '—'}</td>
              </tr>
              {isOpen && (
                <tr className="check-detail-row">
                  <td />
                  <td colSpan={4}>
                    <div className="check-explain">
                      <div>
                        <span className="me-k">怎么验</span>
                        <span className="me-v">{methods[code] || item.method || '（核验方法说明未加载）'}</span>
                      </div>
                      <div>
                        <span className="me-k">本次结论</span>
                        <span className="me-v">{item.detail || '无补充说明'}</span>
                      </div>
                      <div>
                        <span className="me-k">状态含义</span>
                        <span className="me-v">
                          通过＝已验且一致；部分/受限＝只验了一部分；未执行＝缺必要输入；不通过＝验出矛盾，需人工复核
                        </span>
                      </div>
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
