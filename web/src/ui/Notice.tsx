import type { ReactNode } from 'react';

export function Notice({ tone = 'error', children }: { tone?: 'error' | 'info' | 'ok'; children: ReactNode }) {
  return <div className={'notice notice-' + tone}>{children}</div>;
}
