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
