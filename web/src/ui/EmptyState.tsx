import type { ReactNode } from 'react';

type Props = { title: ReactNode; hint?: ReactNode; action?: ReactNode };

export function EmptyState({ title, hint, action }: Props) {
  return (
    <div className="empty-state">
      <p className="empty-state-title">{title}</p>
      {hint ? <p className="empty-state-hint">{hint}</p> : null}
      {action ? <div className="empty-actions">{action}</div> : null}
    </div>
  );
}
