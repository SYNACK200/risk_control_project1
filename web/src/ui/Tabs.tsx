import type { ReactNode } from 'react';

export type TabItem<K extends string> = { key: K; label: ReactNode };

type Props<K extends string> = {
  items: TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  label: string;
  className?: string;
};

/** 页签：value 由调用方（通常是 URL）持有，组件自身不存状态。 */
export function Tabs<K extends string>({ items, value, onChange, label, className = '' }: Props<K>) {
  return (
    <div className={'tabs small-tabs ' + className} role="tablist" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          aria-selected={value === item.key}
          className={value === item.key ? 'active' : ''}
          onClick={() => onChange(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
