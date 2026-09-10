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

{{/* bridge/rag-worker 가 파일로 읽는 Secret 경로 env (코드: *_SECRET_FILE / MATTERMOST_SECRET_DIR) */}}
{{- define "rag.bridgeSecretEnv" -}}
- name: MATTERMOST_OUTGOING_TOKEN_SECRET_FILE
  value: {{ printf "%s/outgoing-token" .Values.secretMounts.bridgeSecretsPath | quote }}
- name: FEEDBACK_SIGNING_KEY_FILE
  value: {{ printf "%s/feedback-signing-key" .Values.secretMounts.bridgeSecretsPath | quote }}
{{- end -}}

{{- define "rag.incomingSecretEnv" -}}
- name: MATTERMOST_SECRET_DIR
  value: {{ .Values.secretMounts.incomingWebhookPath | quote }}
{{- end -}}

{{/* Incoming Webhook Secret 들을 하나의 디렉터리로 투영 — 파일명 = secret_ref (delivery.py 계약) */}}
{{- define "rag.incomingProjectedVolume" -}}
- name: mm-incoming
  projected:
    defaultMode: 0440
    sources:
      {{- range .Values.incomingWebhookSecrets }}
      - secret:
          name: {{ .secretName }}
          items:
            - key: {{ .key | default "url" }}
              path: {{ .secretName }}
      {{- end }}
{{- end -}}
