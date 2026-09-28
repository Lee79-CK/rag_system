import type { NextConfig } from 'next';

// dev 전용: REST 는 Next rewrite 로 chat-gateway 에 same-origin 프록시 (refresh 쿠키 SameSite=Strict 유지).
// K8s 에서는 Ingress 가 /api/v1·/ws → chat-gateway, / → chat-web 으로 라우팅하므로 rewrite 불필요.
const GATEWAY = process.env.CHAT_GATEWAY_URL ?? 'http://localhost:8001';
// Next.js dev 모드(React Refresh·소스맵)는 eval 이 필요하다. 프로덕션은 엄격 유지.
const scriptSrc = process.env.NODE_ENV === 'development' ? "'self' 'unsafe-inline' 'unsafe-eval'" : "'self' 'unsafe-inline'";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // 폐쇄망 배포: `node server.js` 단일 산출물 (.next/standalone) — Helm chat-web 이미지.
  output: 'standalone',
  // dev 와 build 가 같은 .next 를 공유하면 개발 서버가 깨진다 → 출력 디렉터리 분리 (aiops 원본 동일).
  distDir: process.env.NODE_ENV === 'development' ? '.next-dev' : '.next',
  poweredByHeader: false,
  async rewrites() {
    if (process.env.NODE_ENV !== 'development') return [];
    return [{ source: '/api/:path*', destination: `${GATEWAY}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: '/login',
        headers: [
          {
            // 로그인 페이지에 서드파티 리소스 금지 — 폐쇄망: 외부 폰트/CDN 허용 항목 제거
            key: 'Content-Security-Policy',
            value: `default-src 'self'; script-src ${scriptSrc}; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self' ws: wss:; frame-ancestors 'none'`,
          },
        ],
      },
    ];
  },
};

export default nextConfig;
