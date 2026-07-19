import type { CSSProperties, ReactNode } from 'react';

/**
 * Design-system primitives shared across the reconstructed Admin Console screens.
 * Source: docs/admin_console_design_script.md §3 (status palette) + imported design.
 */

export type StatusKind = 'success' | 'info' | 'danger' | 'neutral' | 'warning';

const KIND_STYLE: Record<StatusKind, { bg: string; fg: string; icon: string; spin?: boolean }> = {
  success: { bg: 'var(--tint-success)', fg: 'var(--success-fg)', icon: '✓' },
  info: { bg: 'var(--tint-info)', fg: 'var(--info-fg)', icon: '◔', spin: true },
  danger: { bg: 'var(--tint-danger)', fg: 'var(--danger)', icon: '✕' },
  neutral: { bg: 'var(--tint-neutral)', fg: 'var(--neutral)', icon: '−' },
  warning: { bg: 'var(--tint-warning)', fg: 'var(--warning-fg)', icon: '↻' },
};

/** §3 status → palette-kind mapping. Single source so screens never diverge. */
export function statusKind(status: string): StatusKind {
  const s = (status ?? '').toUpperCase();
  if (['ACTIVE', 'COMPLETED', 'SENT', 'SUCCEEDED', 'SUCCESS', '활성'].includes(s)) return 'success';
  if (['INDEXING', 'RUNNING', 'QUEUED', 'PENDING', 'PROCESSING', 'UPLOADED'].includes(s))
    return 'info';
  if (
    [
      'PARSE_FAILED',
      'INDEX_FAILED',
      'FAILED',
      'DEAD_LETTER',
      'DEADLETTER',
      'DELETED',
      'ERROR',
    ].includes(s)
  )
    return 'danger';
  if (['RETRYING', 'DELIVERY_PENDING'].includes(s)) return 'warning';
  return 'neutral';
}

/** Status pill: color + icon + text (WCAG-AA triple encoding, §1). */
export function StatusBadge({
  status,
  kind,
  label,
}: {
  status?: string;
  kind?: StatusKind;
  label?: ReactNode;
}) {
  const k = kind ?? statusKind(status ?? '');
  const st = KIND_STYLE[k];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '2px 10px',
        borderRadius: 999,
        fontSize: 11.5,
        fontWeight: 700,
        whiteSpace: 'nowrap',
        background: st.bg,
        color: st.fg,
      }}
    >
      <span
        style={
          st.spin
            ? { display: 'inline-block', animation: 'spin 1s linear infinite', lineHeight: 1 }
            : { display: 'inline-block', lineHeight: 1 }
        }
      >
        {st.icon}
      </span>
      {label ?? status}
    </span>
  );
}

/** White surface card matching the design (border + soft shadow + radius). */
export function Surface({
  children,
  style,
  padding = 16,
  onClick,
}: {
  children: ReactNode;
  style?: CSSProperties;
  padding?: number | string;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        boxShadow: 'var(--shadow)',
        padding,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/** Horizontal filter/toolbar bar (search + selects + actions). */
export function FilterBar({ children }: { children: ReactNode }) {
  return (
    <Surface
      padding="12px 16px"
      style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}
    >
      {children}
    </Surface>
  );
}

export function Mono({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <span className="mono" style={style}>
      {children}
    </span>
  );
}
