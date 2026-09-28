'use client';

import { create } from 'zustand';

/** chat-gateway `AuthUser` (rag_schemas.webchat) 와 동일 */
export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: 'user' | 'admin';
  avatar_url: string | null;
  must_change_password: boolean;
}

interface AuthState {
  accessToken: string | null;
  user: AuthUser | null;
  /** refresh 시도 완료 여부 (초기 로드 가드) */
  hydrated: boolean;
  setSession: (token: string, user: AuthUser) => void;
  setHydrated: () => void;
  clear: () => void;
}

/** access token 은 메모리에만 보관. refresh 는 HttpOnly 쿠키(rag_rt). */
export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  hydrated: false,
  setSession: (accessToken, user) => set({ accessToken, user, hydrated: true }),
  setHydrated: () => set({ hydrated: true }),
  clear: () => set({ accessToken: null, user: null, hydrated: true }),
}));
