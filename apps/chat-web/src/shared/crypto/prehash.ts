/**
 * 비밀번호 전송 보호 — 클라이언트 사전 해시(Pre-hash). aiops_chatbot `crypto/prehash.ts` 원본 그대로.
 * 서버 대응 구현: `libs/common/src/rag_common/passwords.py` compute_prehash (고정 벡터로 회귀 테스트).
 *
 *  salt    = SHA-256("aiops-chat:" + workspace_slug + ":" + normalized_email)
 *  prehash = PBKDF2-HMAC-SHA256(password, salt, iterations=600000, 32 bytes)  → base64
 *
 * 브라우저(WebCrypto)와 Node(globalThis.crypto.subtle) 양쪽에서 동일하게 동작한다.
 */
export const PREHASH_ITERATIONS = 600_000;
export const PREHASH_BYTES = 32;

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

function subtle(): SubtleCrypto {
  const c = (globalThis as unknown as { crypto?: Crypto }).crypto;
  if (!c?.subtle) throw new Error('WebCrypto SubtleCrypto is not available in this environment');
  return c.subtle;
}

function toBase64(bytes: Uint8Array): string {
  if (typeof btoa === 'function') {
    let s = '';
    for (const b of bytes) s += String.fromCharCode(b);
    return btoa(s);
  }
  // Node fallback
  return (globalThis as unknown as { Buffer: { from(b: Uint8Array): { toString(e: string): string } } }).Buffer
    .from(bytes)
    .toString('base64');
}

export async function computeSalt(workspaceSlug: string, email: string): Promise<Uint8Array> {
  const enc = new TextEncoder();
  const digest = await subtle().digest(
    'SHA-256',
    enc.encode(`aiops-chat:${workspaceSlug}:${normalizeEmail(email)}`),
  );
  return new Uint8Array(digest);
}

export async function computePrehash(
  workspaceSlug: string,
  email: string,
  password: string,
  iterations: number = PREHASH_ITERATIONS,
): Promise<string> {
  const enc = new TextEncoder();
  const salt = await computeSalt(workspaceSlug, email);
  const key = await subtle().importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveBits']);
  const bits = await subtle().deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt: salt as BufferSource, iterations },
    key,
    PREHASH_BYTES * 8,
  );
  return toBase64(new Uint8Array(bits));
}

/** AUTH-02 비밀번호 정책: 최소 12자, 문자 종류 3종 이상, 이메일·표시명 포함 금지 */
export function validatePasswordPolicy(
  password: string,
  ctx: { email?: string; displayName?: string } = {},
): { ok: true } | { ok: false; reason: string } {
  if (password.length < 12) return { ok: false, reason: '비밀번호는 최소 12자 이상이어야 합니다.' };
  const kinds = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length;
  if (kinds < 3) return { ok: false, reason: '영문 대/소문자·숫자·특수문자 중 3종 이상을 포함해야 합니다.' };
  const lower = password.toLowerCase();
  const local = ctx.email ? normalizeEmail(ctx.email).split('@')[0] : '';
  if (local && local.length >= 3 && lower.includes(local))
    return { ok: false, reason: '비밀번호에 이메일 ID를 포함할 수 없습니다.' };
  if (ctx.displayName && ctx.displayName.length >= 2 && lower.includes(ctx.displayName.toLowerCase()))
    return { ok: false, reason: '비밀번호에 표시명을 포함할 수 없습니다.' };
  return { ok: true };
}
