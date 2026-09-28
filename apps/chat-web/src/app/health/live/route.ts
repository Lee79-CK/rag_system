/** K8s liveness/readiness probe (Helm appServices.chat-web.probePath) — 외부 의존 없음 */
export const dynamic = 'force-dynamic';

export function GET() {
  return Response.json({ status: 'ok' });
}
