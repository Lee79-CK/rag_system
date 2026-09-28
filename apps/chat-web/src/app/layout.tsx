import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import '@/styles/globals.css';
import { Providers } from './providers';

export const metadata: Metadata = {
  title: 'RAG Assistant',
  description: '사내 문서 기반 RAG 챗봇 — 채널별 지식 범위 안에서 근거와 함께 답합니다.',
};

const themeInit = `try{var t=localStorage.getItem('rag.theme');if(t==='dark'||t==='light')document.body.setAttribute('data-theme',t)}catch(e){}`;

// 폐쇄망: 외부 CDN 폰트(Pretendard/IBM Plex Mono) <link> 제거 — globals.css 의 시스템 폰트 fallback 사용.
// 사내 표준 폰트가 필요하면 public/fonts 에 self-host 후 @font-face 로 추가한다.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
