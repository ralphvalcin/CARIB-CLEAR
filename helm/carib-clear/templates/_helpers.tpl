{{- define "carib-clear.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "carib-clear.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Chart.Name .Values.global.environment | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "carib-clear.api.name" -}}
{{- default "api" .Values.api.name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "carib-clear.worker.name" -}}
{{- default "worker" .Values.worker.name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "carib-clear.labels" -}}
app: {{ template "carib-clear.name" . }}
chart: {{ .Chart.Name }}
release: {{ .Release.Name | quote }}
heritage: {{ .Release.Service | quote }}
{{- end }}
