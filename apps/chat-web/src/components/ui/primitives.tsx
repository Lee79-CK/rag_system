'use client';

import clsx from 'clsx';
import { useEffect, useRef, type ReactNode } from 'react';
import { initials } from '@/lib/format';

const AV_COLORS = ['var(--lav2)', 'var(--peach)', 'var(--mint)', 'var(--lav)', 'var(--surface2)'];
export function avatarColor(seed: string, isBot?: boolean): string {
  if (isBot) return 'var(--lav)';
  let h = 0;
  for (const c of seed) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return AV_COLORS[h % AV_COLORS.length];
}

export function Avatar({ name, size = 36, isBot, color, square, className, title }: { name: string; size?: number; isBot?: boolean; color?: string; square?: boolean; className?: string; title?: string }) {
  const bg = color ?? avatarColor(name, isBot);
  const light = bg === 'var(--coral)' || bg === 'var(--lav3)' || bg === 'var(--mint)';
  return (
    <div
      title={title ?? name}
      className={clsx('flex-none flex items-center justify-center font-bold select-none', square ? 'rounded-lg' : 'rounded-full', className)}
      style={{ width: size, height: size, background: bg, color: light ? '#fff' : '#1E1B2E', fontSize: Math.max(9, Math.round(size * 0.3)), fontFamily: isBot ? 'var(--font-mono)' : undefined }}
    >
      {isBot ? name.slice(0, 2).toUpperCase() : initials(name)}
    </div>
  );
}

export type Tone = 'coral' | 'lav' | 'lav2' | 'lav3' | 'mint' | 'muted' | 'ink' | 'surface2' | 'outline' | 'lemon' | 'peach';
const TONE: Record<Tone, { bg: string; fg: string; border?: string }> = {
  coral: { bg: 'var(--coral)', fg: '#fff' },
  lav: { bg: 'var(--lav)', fg: '#1E1B2E' },
  lav2: { bg: 'var(--lav2)', fg: 'var(--ink)' },
  lav3: { bg: 'var(--lav3)', fg: '#fff' },
  mint: { bg: 'var(--mint)', fg: '#fff' },
  muted: { bg: 'var(--surface2)', fg: 'var(--muted)' },
  ink: { bg: 'var(--ink)', fg: 'var(--bg)' },
  surface2: { bg: 'var(--surface2)', fg: 'var(--ink)' },
  outline: { bg: 'transparent', fg: 'var(--muted)', border: '1px solid var(--line)' },
  lemon: { bg: 'var(--lemon)', fg: '#1E1B2E' },
  peach: { bg: 'var(--peach)', fg: '#1E1B2E' },
};
export function Badge({ tone = 'muted', children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  const t = TONE[tone];
  return (
    <span className={clsx('badge', className)} title={title} style={{ background: t.bg, color: t.fg, border: t.border }}>
      {children}
    </span>
  );
}


export function Button({ variant = 'default', size = 'md', className, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'default' | 'primary' | 'danger' | 'ghost'; size?: 'sm' | 'md' | 'lg' }) {
  return <button className={clsx('btn', variant === 'primary' && 'btn-primary', variant === 'danger' && 'btn-danger', variant === 'ghost' && 'btn-ghost', size === 'sm' && '!h-6 !px-2 !text-[11px] !font-medium', size === 'lg' && '!h-9 !px-4 !text-[13px]', className)} {...rest} />;
}

export function Card({ children, className, style }: { children: ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <div className={clsx('card', className)} style={style}>
      {children}
    </div>
  );
}

export function SectionHeader({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center gap-2 px-4 py-3 border-b border-line">
      <b className="text-[13px] font-bold">{title}</b>
      {sub && <span className="mono text-[11px] text-muted">{sub}</span>}
      {right && <div className="ml-auto flex items-center gap-2">{right}</div>}
    </div>
  );
}

/** 3분할 세그먼트 (활성 lav3/#fff) */
export function Segmented<T extends string>({ value, options, onChange, size = 'md', activeInk }: { value: T; options: { value: T; label: ReactNode; title?: string }[]; onChange: (v: T) => void; size?: 'sm' | 'md'; activeInk?: boolean }) {
  return (
    <div className="inline-flex rounded-lg overflow-hidden border border-line" style={{ height: size === 'sm' ? 30 : 34 }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button key={o.value} type="button" title={o.title} onClick={() => onChange(o.value)} className={clsx('px-2.5 text-[11px] font-semibold whitespace-nowrap flex-1', size === 'md' && 'px-3')} style={{ background: on ? (activeInk ? 'var(--ink)' : 'var(--lav3)') : 'transparent', color: on ? (activeInk ? 'var(--bg)' : '#fff') : 'var(--ink)' }}>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange?: (v: boolean) => void; label?: ReactNode; disabled?: boolean }) {
  return (
    <label className={clsx('flex items-center gap-2.5 text-[12px] font-medium select-none', disabled ? 'opacity-60' : 'cursor-pointer')}>
      <span className="relative flex-none rounded-full" style={{ width: 28, height: 16, background: checked ? 'var(--mint)' : 'var(--surface2)', border: '1px solid var(--line)' }} onClick={() => !disabled && onChange?.(!checked)}>
        <span className="absolute top-[1px] rounded-full" style={{ width: 12, height: 12, background: checked ? 'var(--ink)' : 'var(--muted)', left: checked ? 13 : 1, transition: 'left .15s' }} />
      </span>
      {label}
    </label>
  );
}

export function Modal({ open, onClose, children, width = 720, label }: { open: boolean; onClose: () => void; children: ReactNode; width?: number; label?: string }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6" style={{ background: 'rgba(30,27,46,.45)' }} onMouseDown={(e) => e.target === e.currentTarget && onClose()} aria-label={label} role="dialog" aria-modal>
      <div className="flex flex-col animate-fade-up" style={{ width: `min(${width}px,100%)`, maxHeight: '90vh', background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 20, boxShadow: '0 30px 80px rgba(0,0,0,.25)' }}>
        {children}
      </div>
    </div>
  );
}

export function Dropdown({ open, onClose, children, className, align = 'right' }: { open: boolean; onClose: () => void; children: ReactNode; className?: string; align?: 'left' | 'right' }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const t = setTimeout(() => document.addEventListener('mousedown', h));
    return () => {
      clearTimeout(t);
      document.removeEventListener('mousedown', h);
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div ref={ref} className={clsx('absolute top-8 z-20 flex flex-col p-1 text-[12px] font-medium rounded-xl animate-fade-up', align === 'right' ? 'right-0' : 'left-0', className)} style={{ width: 200, background: 'var(--surface)', border: '1px solid var(--line)', boxShadow: '0 12px 40px rgba(0,0,0,.14)' }}>
      {children}
    </div>
  );
}
export function MenuItem({ onClick, children, highlight, danger }: { onClick?: () => void; children: ReactNode; highlight?: boolean; danger?: boolean }) {
  return (
    <button type="button" onClick={onClick} className={clsx('text-left px-2.5 py-2 rounded-lg hover:bg-surface2', highlight && 'font-semibold', danger && 'text-coral')} style={{ background: highlight ? 'var(--lemon2)' : undefined }}>
      {children}
    </button>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return <span className="inline-block rounded-full border-2 border-line border-t-lav3 animate-spin" style={{ width: size, height: size }} />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="p-6 text-center text-[12px] text-muted border border-dashed border-line rounded-xl">{children}</div>;
}

export function Field({ label, children, hint, className }: { label: ReactNode; children: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <label className={clsx('flex flex-col gap-1', className)}>
      <span className="text-[11px] font-semibold text-muted flex justify-between">
        <span>{label}</span>
        {hint && <span className="font-medium">{hint}</span>}
      </span>
      {children}
    </label>
  );
}
