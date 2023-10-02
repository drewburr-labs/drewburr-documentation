{{- define "application.name" -}}
{{- required ".applications[].project must be defined" .name }}
{{- end }}

{{- define "application.namespace" -}}
{{- if dig "destination" "namespace" "" . }}
{{- .destination.namespace }}
{{- else }}
{{- .name }}
{{- end }}
{{- end }}

{{- define "application.project" -}}
{{- default .project "default" }}
{{- end }}

{{- define "application.path" -}}
{{- if dig "source" "path" "" . }}
{{- .source.path }}
{{- else }}
{{- printf "%s%s" "k8s/" .name }}
{{- end }}
{{- end }}

{{- define "application.targetRevision" -}}
{{- if get . "source" }}
{{- default .source.targetRevision }}
{{- end }}
{{- end }}

{{- define "application.syncPolicy" -}}
{{- if .syncPolicy -}}
syncOptions:
    {{/*
    Optional base sync options
    */}}
    {{- if .syncPolicy.syncOptions }}
    {{- .syncPolicy.syncOptions | toYaml }}
    {{- end }}
    {{/*
    Optional additonal sync options
    */}}
    {{- if .syncPolicy.additionalSyncOptions }}
    {{- .syncPolicy.additionalSyncOptions | toYaml }}
    {{- end }}
{{- end }}
{{- end }}
