'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { Toast } from '@/components/ui/Toast';
import { useUiStore } from '@/lib/stores/ui';

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } } }));
  const theme = useUiStore((s) => s.theme);
  useEffect(() => {
    document.body.setAttribute('data-theme', theme);
  }, [theme]);
  return (
    <QueryClientProvider client={client}>
      {children}
      <Toast />
    </QueryClientProvider>
  );
}
