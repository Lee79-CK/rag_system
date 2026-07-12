import { Empty, theme } from 'antd';

export interface BarDatum {
  label: string;
  /** Primary value (e.g. UP). */
  value: number;
  /** Optional secondary stacked value (e.g. DOWN). */
  secondary?: number;
  /** Optional caption below the value (e.g. "88%"). */
  caption?: string;
}

/**
 * Dependency-free horizontal bar chart (inline SVG-free; pure divs).
 * Closed network — no external chart CDN (§7.6). Kept intentionally simple.
 */
export function BarChart({
  data,
  primaryLabel = '긍정',
  secondaryLabel = '부정',
  height = 22,
}: {
  data: BarDatum[];
  primaryLabel?: string;
  secondaryLabel?: string;
  height?: number;
}) {
  const { token } = theme.useToken();
  if (!data.length) {
    return <Empty description="집계 데이터 없음" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  const max = Math.max(1, ...data.map((d) => d.value + (d.secondary ?? 0)));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 16, fontSize: 12, color: token.colorTextSecondary }}>
        <Legend color={token.colorPrimary} label={primaryLabel} />
        <Legend color={token.colorError} label={secondaryLabel} />
      </div>
      {data.map((d) => {
        const total = d.value + (d.secondary ?? 0);
        return (
          <div key={d.label} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div
              style={{
                width: 160,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                fontSize: 13,
              }}
              title={d.label}
            >
              {d.label}
            </div>
            <div
              style={{
                flex: 1,
                display: 'flex',
                height,
                borderRadius: 4,
                overflow: 'hidden',
                background: token.colorFillTertiary,
              }}
            >
              <div
                style={{
                  width: `${(d.value / max) * 100}%`,
                  background: token.colorPrimary,
                }}
              />
              {d.secondary !== undefined && (
                <div
                  style={{
                    width: `${(d.secondary / max) * 100}%`,
                    background: token.colorError,
                  }}
                />
              )}
            </div>
            <div style={{ width: 96, textAlign: 'right', fontSize: 12 }}>
              {d.caption ?? `${total}건`}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 10, height: 10, borderRadius: 2, background: color }} />
      {label}
    </span>
  );
}
