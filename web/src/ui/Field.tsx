import type { InputHTMLAttributes, ReactNode } from 'react';

type Props = InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode };

export function Field({ label, hint, id, ...rest }: Props) {
  const inputId = id ?? 'f-' + label;
  return (
    <div className="field">
      <label htmlFor={inputId}>{label}</label>
      <input id={inputId} {...rest} />
      {hint ? <p className="hint">{hint}</p> : null}
    </div>
  );
}
