{{- define "carib-clear.labels" -}}
app: {{ template "carib-clear.name" . }}
chart: {{ .Chart.Name }}
release: {{ .Release.Name | quote }}
heritage: {{ .Release.Service | quote }}
{{- end -}}
