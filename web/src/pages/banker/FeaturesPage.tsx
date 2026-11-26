import { useCallback, useEffect, useMemo, useState } from 'react';
import { getErrorMessage } from '../../api/errors';
import { listFeatureCatalog, type FeatureCatalogItem } from '../../api/lab';
import { useLabHealth } from '../../hooks/useLabHealth';
import { Button } from '../../ui/Button';
import { EmptyState } from '../../ui/EmptyState';
import { Notice } from '../../ui/Notice';
import { PageHeader } from '../../ui/PageHeader';
import { Table } from '../../ui/Table';

const LAB_PUBLIC_URL: string = import.meta.env.VITE_LAB_PUBLIC_URL || 'http://127.0.0.1:8030/ui';

type Group = { category: string; items: FeatureCatalogItem[] };

/**
 * 特征平台入口页：只放 Lab 服务状态与只读目录。
 * 试算与计算都在独立服务里做，业务系统前端不直连 Lab。
 */
export default function FeaturesPage() {
  const lab = useLabHealth();
  const [items, setItems] = useState<FeatureCatalogItem[] | null>(null);
  const [error, setError] = useState('');
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState('');

  const load = useCallback(() => {
    listFeatureCatalog()
      .then((res) => {
        setItems(res.items ?? []);
        setError('');
      })
      .catch((err) => {
        setItems(null);
        setError(getErrorMessage(err, 'banker'));
      });
  }, []);

  // 目录跟着连接状态走：一变成在线就加载，轮询自己恢复时也不用手动重试
  useEffect(() => {
    if (lab.status === 'up') load();
  }, [lab.status, load]);

  const categories = useMemo(
    () => Array.from(new Set((items ?? []).map((item) => item.category || '未分类'))),
    [items],
  );

  const groups = useMemo<Group[]>(() => {
    const q = keyword.trim().toLowerCase();
    const byCategory = new Map<string, FeatureCatalogItem[]>();
    for (const item of items ?? []) {
      const cat = item.category || '未分类';
      if (category && cat !== category) continue;
      if (q && ![item.code, item.name, item.description ?? ''].some((field) => field.toLowerCase().includes(q))) continue;
      const bucket = byCategory.get(cat);
      if (bucket) bucket.push(item);
      else byCategory.set(cat, [item]);
    }
    return Array.from(byCategory, ([name, list]) => ({ category: name, items: list }));
  }, [items, keyword, category]);

  const up = lab.status === 'up';

  function recheck() {
    lab.refresh();
  }

  return (
    <div className="panel wide">
      <PageHeader
        title="特征平台"
        description="特征计算在独立服务里，这里只做目录与入口；目录为只读，新增或试算请打开特征平台。"
      />

      <section className="feature-card">
        <div className="feature-card-main">
          <span className="feature-card-title">
            <span className={'status-dot ' + (up ? 'ok' : lab.status === 'checking' ? '' : 'bad')} />
            特征服务：{up ? '运行中' : lab.status === 'checking' ? '检测中' : '未连接'}
          </span>
          <span className="muted small">
            {up
              ? `目录版本 ${lab.version ?? '—'}`
              : lab.status === 'checking'
                ? '正在检测特征服务…'
                : '未连接到特征服务，目录暂不可用；请确认 Lab 服务（8030）已启动。'}
          </span>
        </div>
        {up ? (
          <a className="btn btn-primary" href={LAB_PUBLIC_URL} target="_blank" rel="noopener noreferrer">
            打开特征平台 ↗
          </a>
        ) : lab.status === 'down' ? (
          <Button variant="ghost" onClick={recheck}>重新检测</Button>
        ) : (
          <Button disabled>检测中…</Button>
        )}
      </section>

      {error && up ? (
        <Notice>
          目录读取失败：{error}
          <span className="feature-retry">
            <button type="button" className="link-btn" onClick={load}>重试</button>
          </span>
        </Notice>
      ) : null}

      {items === null ? (
        error ? null : <p className="muted">目录加载中…</p>
      ) : items.length === 0 ? (
        <EmptyState title="特征目录是空的" hint="特征服务返回了 0 条特征。" />
      ) : (
        <>
          <div className="filters feature-filters">
            <input
              className="search"
              placeholder="搜索代号 / 名称 / 口径说明"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
            <div className="chips" role="group" aria-label="按分类筛选">
              <button type="button" className={'chip ' + (category ? '' : 'chip-on')} onClick={() => setCategory('')}>
                全部（{items.length}）
              </button>
              {categories.map((name) => (
                <button
                  key={name}
                  type="button"
                  className={'chip ' + (category === name ? 'chip-on' : '')}
                  onClick={() => setCategory(name)}
                >
                  {name}
                </button>
              ))}
            </div>
          </div>

          {groups.length === 0 ? <p className="muted">没有匹配的特征。</p> : null}
          {groups.map((group) => (
            <section key={group.category}>
              <h2>{group.category}（{group.items.length}）</h2>
              <Table compact>
                <thead>
                  <tr><th>代号</th><th>名称</th><th>单位</th><th>口径说明</th></tr>
                </thead>
                <tbody>
                  {group.items.map((item) => (
                    <tr key={item.code}>
                      <td className="mono small">{item.code}</td>
                      <td>{item.name}</td>
                      <td className="small muted">{item.unit || '—'}</td>
                      <td className="small">{item.description || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </section>
          ))}
        </>
      )}
    </div>
  );
}
