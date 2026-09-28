'use client';

import { computePrehash, validatePasswordPolicy } from '@/shared';
import { api } from './api';
import { useAuthStore, type AuthUser } from './stores/auth';

// chat-gateway CHAT_WORKSPACE_SLUG 과 동일해야 한다 (prehash salt 구성요소).
export const WORKSPACE_SLUG = process.env.NEXT_PUBLIC_WORKSPACE_SLUG ?? 'rag';

/** 원문 비밀번호는 브라우저를 떠나지 않는다 — prehash 만 전송 (TDD §7.1.5) */
export async function login(email: string, password: string) {
  const prehash = await computePrehash(WORKSPACE_SLUG, email, password);
  const res = await api<{ access_token: string; user: AuthUser }>('/api/v1/auth/login', {
    method: 'POST',
    noAuth: true,
    body: { email: email.trim().toLowerCase(), prehash, client_nonce: crypto.randomUUID(), timestamp: Date.now() },
  });
  useAuthStore.getState().setSession(res.access_token, res.user);
  return res.user;
}

export async function logout() {
  try {
    await api('/api/v1/auth/logout', { method: 'POST' });
  } finally {
    useAuthStore.getState().clear();
  }
}

export function policyMeta(password: string) {
  const kinds = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length;
  return { length: password.length, kinds };
}

export async function changePassword(email: string, current: string, next: string, displayName?: string) {
  const v = validatePasswordPolicy(next, { email, displayName });
  if (!v.ok) throw new Error(v.reason);
  const [current_prehash, new_prehash] = await Promise.all([computePrehash(WORKSPACE_SLUG, email, current), computePrehash(WORKSPACE_SLUG, email, next)]);
  return api('/api/v1/auth/password/change', { method: 'POST', body: { current_prehash, new_prehash, policy: policyMeta(next) } });
}
