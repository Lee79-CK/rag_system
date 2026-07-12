/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Dev-only reverse-proxy auth header value sent as `X-Auth-User` (docs/TDD.md §7.5, DEC-003). */
  readonly VITE_DEV_AUTH_USER?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
