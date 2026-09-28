'use client';

import { create } from 'zustand';

export type Theme = 'light' | 'dark';
export type ThreadLayout = 'A' | 'B';

interface UiState {
  theme: Theme;
  layout: ThreadLayout;
  toast: string | null;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
  setLayout: (l: ThreadLayout) => void;
  flash: (msg: string) => void;
}

const read = <T>(k: string, d: T): T => {
  try {
    const v = typeof window !== 'undefined' ? window.localStorage.getItem(k) : null;
    return (v as T) ?? d;
  } catch {
    return d;
  }
};
const write = (k: string, v: string) => {
  try {
    window.localStorage.setItem(k, v);
  } catch {
    /* ignore */
  }
};

let toastTimer: ReturnType<typeof setTimeout> | undefined;

export const useUiStore = create<UiState>((set, get) => ({
  theme: read<Theme>('rag.theme', 'light'),
  layout: read<ThreadLayout>('rag.layout', 'A'),
  toast: null,
  setTheme: (theme) => {
    write('rag.theme', theme);
    if (typeof document !== 'undefined') document.body.setAttribute('data-theme', theme);
    set({ theme });
  },
  toggleTheme: () => get().setTheme(get().theme === 'light' ? 'dark' : 'light'),
  setLayout: (layout) => {
    write('rag.layout', layout);
    set({ layout });
  },
  flash: (toast) => {
    set({ toast });
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => set({ toast: null }), 2800);
  },
}));
