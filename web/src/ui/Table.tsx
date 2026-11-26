import type { TableHTMLAttributes } from 'react';

type Props = TableHTMLAttributes<HTMLTableElement> & { compact?: boolean };

export function Table({ compact, className = '', ...rest }: Props) {
  return <table {...rest} className={'grid ' + (compact ? 'compact ' : '') + className} />;
}
