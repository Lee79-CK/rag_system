const TZ = 'Asia/Seoul';

export function fmtTime(d: string | Date | null | undefined): string {
  if (!d) return '';
  const date = typeof d === 'string' ? new Date(d) : d;
  return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: TZ });
}

export function fmtDateLabel(d: string | Date): string {
  const date = typeof d === 'string' ? new Date(d) : d;
  const days = ['일', '월', '화', '수', '목', '금', '토'];
  const ymd = date.toLocaleDateString('sv-SE', { timeZone: TZ });
  const dow = days[new Date(date.toLocaleString('en-US', { timeZone: TZ })).getDay()];
  return `${ymd} (${dow})`;
}

/** 오늘이면 HH:mm, 어제면 '어제', 그 외 MM-DD */
export function fmtRelative(d: string | Date | null | undefined): string {
  if (!d) return '';
  const date = typeof d === 'string' ? new Date(d) : d;
  const today = new Date().toLocaleDateString('sv-SE', { timeZone: TZ });
  const day = date.toLocaleDateString('sv-SE', { timeZone: TZ });
  if (day === today) return fmtTime(date);
  const y = new Date(Date.now() - 86400_000).toLocaleDateString('sv-SE', { timeZone: TZ });
  if (day === y) return '어제';
  return day.slice(5);
}

export function fmtAge(ms: number): string {
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h${m % 60 ? `${m % 60}m` : ''}`;
  const d = Math.floor(h / 24);
  return d === 1 ? '어제' : `${d}d`;
}

export function fmtDateTime(d: string | Date | null | undefined): string {
  if (!d) return '';
  const date = typeof d === 'string' ? new Date(d) : d;
  return date.toLocaleString('ko-KR', { timeZone: TZ, hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export function initials(name: string): string {
  const n = name.trim();
  if (/^[A-Za-z]/.test(n)) return n.slice(0, 2).toUpperCase();
  return n.length <= 2 ? n : n.slice(-2);
}

