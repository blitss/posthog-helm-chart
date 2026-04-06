{{/*
Expand the name of the chart.
*/}}
{{- define "posthog.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "posthog.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "posthog.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "posthog.labels" -}}
helm.sh/chart: {{ include "posthog.chart" . }}
{{ include "posthog.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "posthog.selectorLabels" -}}
app.kubernetes.io/name: {{ include "posthog.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Component labels helper - call with dict "root" . "component" "name"
*/}}
{{- define "posthog.componentLabels" -}}
{{ include "posthog.labels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Component selector labels - call with dict "root" . "component" "name"
*/}}
{{- define "posthog.componentSelectorLabels" -}}
{{ include "posthog.selectorLabels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
ServiceAccount name
*/}}
{{- define "posthog.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "posthog.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Secret name - either user-provided existing secret or chart-managed secret
*/}}
{{- define "posthog.secretName" -}}
{{- if .Values.existingSecret }}
{{- .Values.existingSecret }}
{{- else }}
{{- include "posthog.fullname" . }}-secrets
{{- end }}
{{- end }}

{{/*
Image pull secrets
*/}}
{{- define "posthog.imagePullSecrets" -}}
{{- if .Values.global.imagePullSecrets }}
imagePullSecrets:
{{- toYaml .Values.global.imagePullSecrets | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Pod security context - merges component-level override with global default.
Call with dict "root" . "component" <values-key>
where <values-key> is the values key that has .podSecurityContext (e.g. "web", "postgresql")
*/}}
{{- define "posthog.podSecurityContext" -}}
{{- $componentValues := index .root.Values .component -}}
{{- $componentCtx := $componentValues.podSecurityContext | default dict -}}
{{- $globalCtx := .root.Values.global.podSecurityContext | default dict -}}
{{- $merged := merge $componentCtx $globalCtx -}}
{{- if $merged }}
securityContext:
  {{- toYaml $merged | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Container security context - merges component-level override with global default.
Call with dict "root" . "component" <values-key>
*/}}
{{- define "posthog.containerSecurityContext" -}}
{{- $componentValues := index .root.Values .component -}}
{{- $componentCtx := $componentValues.containerSecurityContext | default dict -}}
{{- $globalCtx := .root.Values.global.containerSecurityContext | default dict -}}
{{- $merged := merge $componentCtx $globalCtx -}}
{{- if $merged }}
securityContext:
  {{- toYaml $merged | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Node selector - merges component-level with global.
Call with dict "root" . "component" <values-key>
*/}}
{{- define "posthog.nodeSelector" -}}
{{- $componentValues := index .root.Values .component -}}
{{- $componentNS := $componentValues.nodeSelector | default dict -}}
{{- $globalNS := .root.Values.global.nodeSelector | default dict -}}
{{- $merged := merge $componentNS $globalNS -}}
{{- if $merged }}
nodeSelector:
  {{- toYaml $merged | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Tolerations - component-level overrides global (not merged, replaced).
Call with dict "root" . "component" <values-key>
*/}}
{{- define "posthog.tolerations" -}}
{{- $componentValues := index .root.Values .component -}}
{{- $tols := $componentValues.tolerations | default .root.Values.global.tolerations -}}
{{- if $tols }}
tolerations:
  {{- toYaml $tols | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Affinity - component-level overrides global (not merged, replaced).
Call with dict "root" . "component" <values-key>
*/}}
{{- define "posthog.affinity" -}}
{{- $componentValues := index .root.Values .component -}}
{{- $aff := $componentValues.affinity | default .root.Values.global.affinity -}}
{{- if $aff }}
affinity:
  {{- toYaml $aff | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Pod annotations - merges component-level with global.
Call with dict "root" . "component" <values-key>
*/}}
{{- define "posthog.podAnnotations" -}}
{{- $componentValues := index .root.Values .component -}}
{{- $componentAnn := $componentValues.podAnnotations | default dict -}}
{{- $globalAnn := .root.Values.global.podAnnotations | default dict -}}
{{- $merged := merge $componentAnn $globalAnn -}}
{{- if $merged }}
{{- toYaml $merged }}
{{- end }}
{{- end }}

{{/*
Database secret name - returns the secret that contains the database URL
*/}}
{{- define "posthog.databaseSecretName" -}}
{{- if .Values.postgresql.enabled -}}
{{ include "posthog.secretName" . }}
{{- else if .Values.externalPostgresql.secretName -}}
{{ .Values.externalPostgresql.secretName }}
{{- else -}}
{{ include "posthog.fullname" . }}-app
{{- end -}}
{{- end }}

{{/*
Database secret key - returns the key in the secret that contains the database URL
*/}}
{{- define "posthog.databaseSecretKey" -}}
{{- if .Values.postgresql.enabled -}}
database-url
{{- else if .Values.externalPostgresql.secretName -}}
{{ .Values.externalPostgresql.uriKey | default "uri" }}
{{- else -}}
uri
{{- end -}}
{{- end }}

{{/*
Common environment variables shared across PostHog application services
*/}}
{{- define "posthog.commonEnv" -}}
- name: SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: posthog-secret
- name: ENCRYPTION_SALT_KEYS
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: encryption-salt-keys
{{- if .Values.postgresql.enabled }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: database-url
{{- else if .Values.externalPostgresql.url }}
- name: DATABASE_URL
  value: {{ .Values.externalPostgresql.url | quote }}
{{- else if .Values.externalPostgresql.secretName }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalPostgresql.secretName | quote }}
      key: {{ .Values.externalPostgresql.uriKey | default "uri" | quote }}
{{- else }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.fullname" . }}-app
      key: uri
{{- end }}
- name: REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: redis-url
- name: CLICKHOUSE_HOST
  value: {{ .Values.externalClickhouse.host | default (printf "%s-clickhouse" (include "posthog.fullname" .)) | quote }}
- name: CLICKHOUSE_LOGS_HOST
  value: {{ .Values.externalClickhouse.host | default (printf "%s-clickhouse" (include "posthog.fullname" .)) | quote }}
- name: CLICKHOUSE_LOGS_CLUSTER_HOST
  value: {{ .Values.externalClickhouse.host | default (printf "%s-clickhouse" (include "posthog.fullname" .)) | quote }}
- name: CLICKHOUSE_LOGS_CLUSTER_PORT
  value: {{ .Values.externalClickhouse.logsPort | default "9000" | quote }}
- name: CLICKHOUSE_DATABASE
  value: {{ .Values.clickhouse.database | default "posthog" | quote }}
- name: CLICKHOUSE_LOGS_DATABASE
  value: {{ .Values.externalClickhouse.logsDatabase | default "default" | quote }}
- name: CLICKHOUSE_SECURE
  value: {{ .Values.clickhouse.secure | default "false" | quote }}
- name: CLICKHOUSE_LOGS_CLUSTER_SECURE
  value: {{ .Values.clickhouse.secure | default "false" | quote }}
- name: CLICKHOUSE_VERIFY
  value: {{ .Values.clickhouse.verify | default "false" | quote }}
{{- if .Values.clickhouse.enabled }}
- name: CLICKHOUSE_API_USER
  value: {{ .Values.clickhouse.apiUser | default "api" | quote }}
- name: CLICKHOUSE_API_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: clickhouse-api-password
- name: CLICKHOUSE_APP_USER
  value: {{ .Values.clickhouse.appUser | default "app" | quote }}
- name: CLICKHOUSE_APP_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: clickhouse-app-password
- name: CLICKHOUSE_LOGS_CLUSTER_USER
  value: {{ .Values.clickhouse.appUser | default "app" | quote }}
- name: CLICKHOUSE_LOGS_CLUSTER_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: clickhouse-app-password
{{- else }}
- name: CLICKHOUSE_API_USER
  value: {{ .Values.externalClickhouse.apiUser | default .Values.externalClickhouse.user | default "default" | quote }}
- name: CLICKHOUSE_API_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalClickhouse.secretName | quote }}
      key: {{ .Values.externalClickhouse.secretPasswordKey | default "password" | quote }}
- name: CLICKHOUSE_APP_USER
  value: {{ .Values.externalClickhouse.appUser | default .Values.externalClickhouse.user | default "default" | quote }}
- name: CLICKHOUSE_APP_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalClickhouse.secretName | quote }}
      key: {{ .Values.externalClickhouse.secretPasswordKey | default "password" | quote }}
- name: CLICKHOUSE_LOGS_CLUSTER_USER
  value: {{ .Values.externalClickhouse.appUser | default .Values.externalClickhouse.user | default "default" | quote }}
- name: CLICKHOUSE_LOGS_CLUSTER_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalClickhouse.secretName | quote }}
      key: {{ .Values.externalClickhouse.secretPasswordKey | default "password" | quote }}
{{- end }}
- name: CLICKHOUSE_USER
  value: {{ .Values.externalClickhouse.user | default .Values.externalClickhouse.appUser | default .Values.externalClickhouse.apiUser | default (.Values.clickhouse.apiUser | default "default") | quote }}
{{- if .Values.clickhouse.enabled }}
- name: CLICKHOUSE_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: clickhouse-api-password
{{- else }}
- name: CLICKHOUSE_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalClickhouse.secretName | quote }}
      key: {{ .Values.externalClickhouse.secretPasswordKey | default "password" | quote }}
- name: CLICKHOUSE_CLUSTER
  value: {{ .Values.externalClickhouse.cluster | default "default" | quote }}
- name: CLICKHOUSE_MIGRATIONS_CLUSTER
  value: {{ .Values.externalClickhouse.migrationsCluster | default .Values.externalClickhouse.cluster | default "default" | quote }}
- name: CLICKHOUSE_SINGLE_SHARD_CLUSTER
  value: {{ .Values.externalClickhouse.singleShardCluster | default .Values.externalClickhouse.cluster | default "default" | quote }}
- name: CLICKHOUSE_WRITABLE_CLUSTER
  value: {{ .Values.externalClickhouse.writableCluster | default .Values.externalClickhouse.cluster | default "default" | quote }}
- name: CLICKHOUSE_PRIMARY_REPLICA_CLUSTER
  value: {{ .Values.externalClickhouse.primaryReplicaCluster | default .Values.externalClickhouse.cluster | default "default" | quote }}
- name: CLICKHOUSE_LOGS_CLUSTER
  value: {{ .Values.externalClickhouse.logsCluster | default .Values.externalClickhouse.singleShardCluster | default .Values.externalClickhouse.cluster | default "default" | quote }}
- name: CLICKHOUSE_SATELLITE_CLUSTERS
  value: {{ .Values.externalClickhouse.satelliteClusters | default "" | quote }}
{{- end }}
- name: KAFKA_HOSTS
  value: {{ .Values.externalKafka.brokers | default (printf "%s-kafka:9092" (include "posthog.fullname" .)) | quote }}
- name: KAFKA_PRODUCER_METADATA_BROKER_LIST
  value: {{ .Values.externalKafka.brokers | default (printf "%s-kafka:9092" (include "posthog.fullname" .)) | quote }}
- name: KAFKA_CONSUMER_METADATA_BROKER_LIST
  value: {{ .Values.externalKafka.brokers | default (printf "%s-kafka:9092" (include "posthog.fullname" .)) | quote }}
- name: KAFKA_CDP_PRODUCER_METADATA_BROKER_LIST
  value: {{ .Values.externalKafka.brokers | default (printf "%s-kafka:9092" (include "posthog.fullname" .)) | quote }}
- name: KAFKA_WARPSTREAM_PRODUCER_METADATA_BROKER_LIST
  value: {{ .Values.externalKafka.brokers | default (printf "%s-kafka:9092" (include "posthog.fullname" .)) | quote }}
- name: KAFKA_METRICS_PRODUCER_METADATA_BROKER_LIST
  value: {{ .Values.externalKafka.brokers | default (printf "%s-kafka:9092" (include "posthog.fullname" .)) | quote }}
- name: KAFKA_WAREHOUSE_PRODUCER_METADATA_BROKER_LIST
  value: {{ .Values.externalKafka.brokers | default (printf "%s-kafka:9092" (include "posthog.fullname" .)) | quote }}
- name: SITE_URL
  value: {{ printf "https://%s" .Values.ingress.hostname | quote }}
- name: DEPLOYMENT
  value: "helm"
- name: IS_BEHIND_PROXY
  value: "true"
- name: DISABLE_SECURE_SSL_REDIRECT
  value: "true"
- name: OTEL_SDK_DISABLED
  value: "true"
- name: OPT_OUT_CAPTURE
  value: {{ .Values.posthog.optOutCapture | default "false" | quote }}
- name: OBJECT_STORAGE_ENABLED
  value: {{ .Values.objectStorage.enabled | default "true" | quote }}
- name: OBJECT_STORAGE_ENDPOINT
  value: {{ .Values.externalObjectStorage.endpoint | default (printf "http://%s-minio:9000" (include "posthog.fullname" .)) | quote }}
- name: OBJECT_STORAGE_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: object-storage-access-key
- name: OBJECT_STORAGE_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: object-storage-secret-key
- name: OBJECT_STORAGE_BUCKET
  value: "posthog"
- name: OBJECT_STORAGE_PUBLIC_ENDPOINT
  value: {{ printf "https://%s" .Values.ingress.hostname | quote }}
- name: OBJECT_STORAGE_REGION
  value: "auto"
- name: OBJECT_STORAGE_FORCE_PATH_STYLE
  value: "true"
- name: SESSION_RECORDING_V2_S3_ENDPOINT
  value: {{ .Values.externalSeaweedfs.endpoint | default (printf "http://%s-seaweedfs:8333" (include "posthog.fullname" .)) | quote }}
- name: SESSION_RECORDING_V2_S3_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: seaweedfs-access-key
- name: SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: seaweedfs-secret-key
- name: SESSION_RECORDING_V2_S3_REGION
  value: "auto"
- name: SESSION_RECORDING_V2_S3_BUCKET
  value: "posthog"
- name: TEMPORAL_HOST
  value: {{ .Values.externalTemporal.host | default (printf "%s-temporal" (include "posthog.fullname" .)) | quote }}
{{- if .Values.postgresql.enabled }}
- name: CYCLOTRON_DATABASE_URL
  value: {{ printf "postgres://%s:%s@%s-postgresql:5432/cyclotron" .Values.postgresql.auth.username .Values.postgresql.auth.password (include "posthog.fullname" .) | quote }}
{{- else if .Values.externalPostgresql.cyclotronUrl }}
- name: CYCLOTRON_DATABASE_URL
  value: {{ .Values.externalPostgresql.cyclotronUrl | quote }}
{{- else if .Values.externalPostgresql.secretName }}
- name: CYCLOTRON_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalPostgresql.secretName | quote }}
      key: {{ .Values.externalPostgresql.cyclotronUriKey | default "cyclotron-uri" | quote }}
{{- else }}
- name: _CNPG_USER
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.fullname" . }}-app
      key: username
- name: _CNPG_PASS
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.fullname" . }}-app
      key: password
- name: CYCLOTRON_DATABASE_URL
  value: {{ printf "postgres://$(_CNPG_USER):$(_CNPG_PASS)@%s-rw:5432/cyclotron" (include "posthog.fullname" .) | quote }}
{{- end }}
{{- if .Values.postgresql.enabled }}
- name: PERSONS_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: database-url
{{- else if .Values.externalPostgresql.personsUrl }}
- name: PERSONS_DATABASE_URL
  value: {{ .Values.externalPostgresql.personsUrl | quote }}
{{- else if .Values.externalPostgresql.url }}
- name: PERSONS_DATABASE_URL
  value: {{ .Values.externalPostgresql.url | quote }}
{{- else if .Values.externalPostgresql.secretName }}
- name: PERSONS_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalPostgresql.secretName | quote }}
      key: {{ .Values.externalPostgresql.personsUriKey | default "persons-uri" | quote }}
{{- else }}
- name: PERSONS_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.fullname" . }}-app
      key: uri
{{- end }}
- name: CDP_API_URL
  value: {{ printf "http://%s-plugins:6738" (include "posthog.fullname" .) | quote }}
- name: RECORDING_API_URL
  value: {{ printf "http://%s-recording-api:6738" (include "posthog.fullname" .) | quote }}
- name: FEATURE_FLAGS_SERVICE_URL
  value: {{ printf "http://%s-feature-flags:3001" (include "posthog.fullname" .) | quote }}
- name: LIVESTREAM_HOST
  value: {{ printf "https://%s/livestream" .Values.ingress.hostname | quote }}
- name: FLAGS_REDIS_ENABLED
  value: "false"
{{- with .Values.global.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
PostgreSQL connection URL builder
*/}}
{{- define "posthog.databaseUrl" -}}
{{- if .Values.externalPostgresql.url -}}
{{- .Values.externalPostgresql.url -}}
{{- else -}}
{{- printf "postgres://%s:%s@%s-postgresql:5432/%s" .Values.postgresql.auth.username .Values.postgresql.auth.password (include "posthog.fullname" .) .Values.postgresql.auth.database -}}
{{- end -}}
{{- end }}

{{/*
Redis URL builder
*/}}
{{- define "posthog.redisUrl" -}}
{{- if .Values.externalRedis.url -}}
{{- .Values.externalRedis.url -}}
{{- else -}}
{{- printf "redis://%s-redis:6379/" (include "posthog.fullname" .) -}}
{{- end -}}
{{- end }}

{{/*
Topology spread constraints for HA - preferred spread across zones and nodes.
Call with dict "root" . "component" "name" where name is the component label value.
*/}}
{{- define "posthog.topologySpreadConstraints" -}}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        {{- include "posthog.componentSelectorLabels" (dict "root" .root "component" .component) | nindent 8 }}
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        {{- include "posthog.componentSelectorLabels" (dict "root" .root "component" .component) | nindent 8 }}
{{- end }}
