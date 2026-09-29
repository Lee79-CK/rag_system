{{/* 공통 헬퍼 — docs/TDD.md §14 */}}

{{- define "rag.image" -}}
{{- printf "%s/%s:%s" $.root.Values.global.imageRegistry .image ($.root.Values.global.imageTag | toString) -}}
{{- end -}}

{{- define "rag.labels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/part-of: rag-platform
app.kubernetes.io/managed-by: {{ $.root.Release.Service }}
{{- end -}}

{{/* offline 환경변수 (§3.4) */}}
{{- define "rag.offlineEnv" -}}
{{- range $k, $v := .Values.global.offlineEnv }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- end -}}

{{/* PostgreSQL 접속 env (TDD §10 키). 비밀번호는 사전 생성 Secret(global.postgres.existingSecret, key=password). */}}
{{- define "rag.dbEnv" -}}
- name: POSTGRES_HOST
  value: {{ .Values.global.postgres.host | quote }}
- name: POSTGRES_PORT
  value: {{ .Values.global.postgres.port | quote }}
- name: POSTGRES_USER
  value: {{ .Values.global.postgres.user | quote }}
- name: POSTGRES_DB
  value: {{ .Values.global.postgres.db | quote }}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.global.postgres.existingSecret }}
      key: password
{{- end -}}

{{/* Redis env — 앱(REDIS_URL) + rq CLI(RQ_REDIS_URL) */}}
{{- define "rag.redisEnv" -}}
- name: REDIS_URL
  value: {{ .Values.global.redisUrl | quote }}
- name: RQ_REDIS_URL
  value: {{ .Values.global.redisUrl | quote }}
{{- end -}}

{{/* Web Chat Secret(global.chatSecretName) 키 → 코드가 읽는 *_FILE env (TDD §10, §14).
     서비스별 appServices.<svc>.secretMount.keys 에 필요한 키만 나열 → 해당 파일만 마운트(최소 권한). */}}
{{- define "rag.chatSecretEnvName" -}}
{{- $m := dict "jwt-secret" "JWT_SECRET_FILE" "password-pepper" "PASSWORD_PEPPER_FILE" "feedback-signing-key" "FEEDBACK_SIGNING_KEY_FILE" -}}
{{- required (printf "unknown secretMount key %q (jwt-secret|password-pepper|feedback-signing-key)" .) (get $m .) -}}
{{- end -}}

{{- define "rag.chatSecretEnv" -}}
{{- $path := .svc.secretMount.mountPath | default .root.Values.secretMounts.chatSecretsPath -}}
{{- range .svc.secretMount.keys }}
- name: {{ include "rag.chatSecretEnvName" . }}
  value: {{ printf "%s/%s" $path . | quote }}
{{- end }}
{{- end -}}
