import type { ReactNode } from 'react';

type Props = { title?: ReactNode; description?: ReactNode; actions?: ReactNode };

/** 统一页头：h1 + 一句职责说明 + 右侧主操作。嵌入别的页面时省略 title，只留说明与操作。 */
export function PageHeader({ title, description, actions }: Props) {
  return (
    <header className={'panel-head' + (title ? '' : ' no-title')}>
      <div>
        {title ? <h1>{title}</h1> : null}
        {description ? <p className="sub">{description}</p> : null}
      </div>
      {actions}
    </header>
  );
}
