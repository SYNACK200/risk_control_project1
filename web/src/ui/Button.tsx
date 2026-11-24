import type { ButtonHTMLAttributes } from 'react';

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md';
  block?: boolean;
};

export function Button({ variant = 'primary', size = 'md', block, className = '', ...rest }: Props) {
  const classes = [
    'btn',
    'btn-' + variant,
    size === 'sm' ? 'btn-sm' : '',
    block ? 'btn-block' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  return <button {...rest} className={classes} />;
}
