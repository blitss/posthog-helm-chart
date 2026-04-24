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
Resolve an image reference for a component, falling back to another component's image
configuration when the component-local image fields are empty.
Call with dict "root" . "component" <values-key> "fallbackComponent" <values-key>
*/}}
{{- define "posthog.imageRef" -}}
{{- $componentValues := (index .root.Values .component) | default dict -}}
{{- $componentImage := $componentValues.image | default dict -}}
{{- $fallbackValues := (index .root.Values .fallbackComponent) | default dict -}}
{{- $fallbackImage := $fallbackValues.image | default dict -}}
{{- $repository := default $fallbackImage.repository $componentImage.repository -}}
{{- $tag := default $fallbackImage.tag $componentImage.tag -}}
{{- printf "%s:%s" $repository $tag -}}
{{- end }}

{{/*
Resolve image pull policy for a component, falling back to another component's image
configuration when the component-local pullPolicy is empty.
Call with dict "root" . "component" <values-key> "fallbackComponent" <values-key>
*/}}
{{- define "posthog.imagePullPolicy" -}}
{{- $componentValues := (index .root.Values .component) | default dict -}}
{{- $componentImage := $componentValues.image | default dict -}}
{{- $fallbackValues := (index .root.Values .fallbackComponent) | default dict -}}
{{- $fallbackImage := $fallbackValues.image | default dict -}}
{{- default ($fallbackImage.pullPolicy | default "Always") $componentImage.pullPolicy -}}
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
{{- else if and .Values.externalPostgresql.secretName (not .Values.externalPostgresql.host) -}}
{{ .Values.externalPostgresql.secretName }}
{{- else -}}
{{ include "posthog.fullname" . }}-app
{{- end -}}
{{- end }}

{{/*
Traefik path rule that matches exactly /path or anything below /path/.
Call with a path string such as "/s".
*/}}
{{- define "posthog.traefikPathRule" -}}
{{- $path := . -}}
{{ printf "(Path(`%s`) || PathPrefix(`%s/`))" $path $path }}
{{- end }}

{{/*
Istio URI match entries for exactly /path and anything below /path/.
Call with a path string such as "/s".
*/}}
{{- define "posthog.istioPathMatches" -}}
{{- $path := . -}}
- uri:
    exact: {{ $path }}
- uri:
    prefix: {{ printf "%s/" $path }}
{{- end }}

{{/*
Gateway API path matches for exactly /path and anything below /path/.
Call with a path string such as "/s".
*/}}
{{- define "posthog.gatewayPathMatches" -}}
{{- $path := . -}}
- path:
    type: Exact
    value: {{ $path }}
- path:
    type: PathPrefix
    value: {{ printf "%s/" $path }}
{{- end }}

{{/*
Database secret key - returns the key in the secret that contains the database URL
*/}}
{{- define "posthog.databaseSecretKey" -}}
{{- if .Values.postgresql.enabled -}}
database-url
{{- else if and .Values.externalPostgresql.secretName (not .Values.externalPostgresql.host) -}}
{{ .Values.externalPostgresql.uriKey | default "uri" }}
{{- else -}}
uri
{{- end -}}
{{- end }}

{{/*
Whether external Postgres URLs should be assembled from a generated credential secret
*/}}
{{- define "posthog.externalPostgresqlUseCredentialSecret" -}}
{{- if and (not .Values.postgresql.enabled) .Values.externalPostgresql.secretName .Values.externalPostgresql.host -}}
true
{{- end -}}
{{- end }}

{{/*
Shared external Postgres credential env vars
*/}}
{{- define "posthog.externalPostgresqlCredentialEnv" -}}
{{- if include "posthog.externalPostgresqlUseCredentialSecret" . }}
- name: _POSTHOG_PG_USER
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalPostgresql.secretName | quote }}
      key: {{ .Values.externalPostgresql.usernameKey | default "username" | quote }}
- name: _POSTHOG_PG_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalPostgresql.secretName | quote }}
      key: {{ .Values.externalPostgresql.passwordKey | default "password" | quote }}
{{- end }}
{{- end }}

{{/*
Builds a postgres URL from the generated credential secret
Call with dict "root" . "database" "<db-name>"
*/}}
{{- define "posthog.externalPostgresqlUrlValue" -}}
{{- $root := .root -}}
{{- $database := .database -}}
{{ printf "postgres://$(_POSTHOG_PG_USER):$(_POSTHOG_PG_PASSWORD)@%s:%v/%s" $root.Values.externalPostgresql.host ($root.Values.externalPostgresql.port | default 5432) $database }}
{{- end }}

{{/*
Canonical ClickHouse database names.
*/}}
{{- define "posthog.clickhouseDatabase" -}}
{{- .Values.clickhouse.database | default "posthog" -}}
{{- end }}

{{- define "posthog.clickhouseLogsDatabase" -}}
{{- .Values.externalClickhouse.logsDatabase | default "default" -}}
{{- end }}

{{- define "posthog.clickhouseHost" -}}
{{- if .Values.clickhouse.enabled -}}
{{- printf "%s-clickhouse" (include "posthog.fullname" .) -}}
{{- else -}}
{{- required "externalClickhouse.host is required when clickhouse.enabled=false" .Values.externalClickhouse.host -}}
{{- end -}}
{{- end }}

{{- define "posthog.clickhouseUser" -}}
{{- if .Values.clickhouse.enabled -}}
{{- .Values.clickhouse.apiUser | default "api" -}}
{{- else -}}
{{- .Values.externalClickhouse.user | default .Values.externalClickhouse.appUser | default .Values.externalClickhouse.apiUser | default "default" -}}
{{- end -}}
{{- end }}

{{/*
Canonical ClickHouse cluster names.
*/}}
{{- define "posthog.clickhouseCluster" -}}
{{- .Values.externalClickhouse.cluster | default "default" -}}
{{- end }}

{{- define "posthog.clickhouseMigrationsCluster" -}}
{{- .Values.externalClickhouse.migrationsCluster | default (include "posthog.clickhouseCluster" .) -}}
{{- end }}

{{- define "posthog.clickhouseSingleShardCluster" -}}
{{- .Values.externalClickhouse.singleShardCluster | default (include "posthog.clickhouseCluster" .) -}}
{{- end }}

{{- define "posthog.clickhouseWritableCluster" -}}
{{- .Values.externalClickhouse.writableCluster | default (include "posthog.clickhouseCluster" .) -}}
{{- end }}

{{- define "posthog.clickhousePrimaryReplicaCluster" -}}
{{- .Values.externalClickhouse.primaryReplicaCluster | default (include "posthog.clickhouseCluster" .) -}}
{{- end }}

{{- define "posthog.clickhouseLogsCluster" -}}
{{- .Values.externalClickhouse.logsCluster | default (include "posthog.clickhouseSingleShardCluster" .) -}}
{{- end }}

{{/*
Returns true when a posthog.env or posthog.secretEnv override exists for a name
*/}}
{{- define "posthog.hasEnvOverride" -}}
{{- $root := .root -}}
{{- $name := .name -}}
{{- if or (and $root.Values.posthog.env (hasKey $root.Values.posthog.env $name)) (and $root.Values.posthog.secretEnv (hasKey $root.Values.posthog.secretEnv $name)) -}}
true
{{- end -}}
{{- end }}

{{/*
Renders one environment variable from posthog.secretEnv or posthog.env
Secret-backed values take precedence over plain values.
*/}}
{{- define "posthog.renderEnvOverride" -}}
{{- $root := .root -}}
{{- $name := .name -}}
{{- if and $root.Values.posthog.secretEnv (hasKey $root.Values.posthog.secretEnv $name) -}}
{{- $ref := get $root.Values.posthog.secretEnv $name -}}
- name: {{ $name }}
  valueFrom:
    secretKeyRef:
      name: {{ required (printf "posthog.secretEnv.%s.name is required" $name) $ref.name | quote }}
      key: {{ required (printf "posthog.secretEnv.%s.key is required" $name) $ref.key | quote }}
      {{- if hasKey $ref "optional" }}
      optional: {{ $ref.optional }}
      {{- end }}
{{- else if and $root.Values.posthog.env (hasKey $root.Values.posthog.env $name) -}}
- name: {{ $name }}
  value: {{ printf "%v" (get $root.Values.posthog.env $name) | quote }}
{{- end -}}
{{- end }}

{{/*
Renders all remaining custom env vars except the excluded names.
*/}}
{{- define "posthog.renderRemainingCustomEnv" -}}
{{- $root := .root -}}
{{- $excluded := .excluded | default (list) -}}
{{- if $root.Values.posthog.secretEnv }}
{{- range $name := keys $root.Values.posthog.secretEnv | sortAlpha }}
{{- if not (has $name $excluded) }}
{{ include "posthog.renderEnvOverride" (dict "root" $root "name" $name) }}
{{- end }}
{{- end }}
{{- end }}
{{- if $root.Values.posthog.env }}
{{- range $name := keys $root.Values.posthog.env | sortAlpha }}
{{- if and (not (has $name $excluded)) (not (and $root.Values.posthog.secretEnv (hasKey $root.Values.posthog.secretEnv $name))) }}
- name: {{ $name }}
  value: {{ printf "%v" (get $root.Values.posthog.env $name) | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common environment variables shared across PostHog application services
*/}}
{{- define "posthog.commonEnv" -}}
{{- $overridableEnvNames := list "SECRET_KEY" "DATABASE_URL" "REDIS_URL" "SITE_URL" "IS_BEHIND_PROXY" "DISABLE_SECURE_SSL_REDIRECT" "OPT_OUT_CAPTURE" "OBJECT_STORAGE_PUBLIC_ENDPOINT" "CYCLOTRON_DATABASE_URL" "PERSONS_DATABASE_URL" -}}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "SECRET_KEY") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "SECRET_KEY") }}
{{- else }}
- name: SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: posthog-secret
{{- end }}
- name: ENCRYPTION_SALT_KEYS
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: encryption-salt-keys
{{- include "posthog.externalPostgresqlCredentialEnv" . }}
{{- if .Values.postgresql.enabled }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "DATABASE_URL") }}
{{- else }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: database-url
{{- end }}
{{- else if .Values.externalPostgresql.url }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "DATABASE_URL") }}
{{- else }}
- name: DATABASE_URL
  value: {{ .Values.externalPostgresql.url | quote }}
{{- end }}
{{- else if include "posthog.externalPostgresqlUseCredentialSecret" . }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "DATABASE_URL") }}
{{- else }}
- name: DATABASE_URL
  value: {{ include "posthog.externalPostgresqlUrlValue" (dict "root" . "database" (.Values.externalPostgresql.database | default "posthog")) | quote }}
{{- end }}
{{- else if .Values.externalPostgresql.secretName }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "DATABASE_URL") }}
{{- else }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalPostgresql.secretName | quote }}
      key: {{ .Values.externalPostgresql.uriKey | default "uri" | quote }}
{{- end }}
{{- else }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "DATABASE_URL") }}
{{- else }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.fullname" . }}-app
      key: uri
{{- end }}
{{- end }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "REDIS_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "REDIS_URL") }}
{{- else }}
- name: REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: redis-url
{{- end }}
- name: CLICKHOUSE_HOST
  value: {{ include "posthog.clickhouseHost" . | quote }}
- name: CLICKHOUSE_LOGS_HOST
  value: {{ include "posthog.clickhouseHost" . | quote }}
- name: CLICKHOUSE_LOGS_CLUSTER_HOST
  value: {{ include "posthog.clickhouseHost" . | quote }}
- name: CLICKHOUSE_LOGS_CLUSTER_PORT
  value: {{ .Values.externalClickhouse.logsPort | default "9000" | quote }}
- name: CLICKHOUSE_DATABASE
  value: {{ include "posthog.clickhouseDatabase" . | quote }}
- name: CLICKHOUSE_LOGS_DATABASE
  value: {{ include "posthog.clickhouseLogsDatabase" . | quote }}
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
  value: {{ include "posthog.clickhouseUser" . | quote }}
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
  value: {{ include "posthog.clickhouseCluster" . | quote }}
- name: CLICKHOUSE_MIGRATIONS_CLUSTER
  value: {{ include "posthog.clickhouseMigrationsCluster" . | quote }}
- name: CLICKHOUSE_SINGLE_SHARD_CLUSTER
  value: {{ include "posthog.clickhouseSingleShardCluster" . | quote }}
- name: CLICKHOUSE_WRITABLE_CLUSTER
  value: {{ include "posthog.clickhouseWritableCluster" . | quote }}
- name: CLICKHOUSE_PRIMARY_REPLICA_CLUSTER
  value: {{ include "posthog.clickhousePrimaryReplicaCluster" . | quote }}
- name: CLICKHOUSE_LOGS_CLUSTER
  value: {{ include "posthog.clickhouseLogsCluster" . | quote }}
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
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "SITE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "SITE_URL") }}
{{- else }}
- name: SITE_URL
  value: {{ printf "https://%s" .Values.ingress.hostname | quote }}
{{- end }}
- name: DEPLOYMENT
  value: "helm"
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "IS_BEHIND_PROXY") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "IS_BEHIND_PROXY") }}
{{- else }}
- name: IS_BEHIND_PROXY
  value: "true"
{{- end }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "DISABLE_SECURE_SSL_REDIRECT") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "DISABLE_SECURE_SSL_REDIRECT") }}
{{- else }}
- name: DISABLE_SECURE_SSL_REDIRECT
  value: "true"
{{- end }}
- name: OTEL_SDK_DISABLED
  value: "true"
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "OPT_OUT_CAPTURE") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "OPT_OUT_CAPTURE") }}
{{- else }}
- name: OPT_OUT_CAPTURE
  value: {{ .Values.posthog.optOutCapture | default "false" | quote }}
{{- end }}
- name: OBJECT_STORAGE_ENABLED
  value: {{ .Values.objectStorage.enabled | default "true" | quote }}
- name: OBJECT_STORAGE_ENDPOINT
{{- if .Values.rustfs.enabled }}
  value: {{ printf "http://%s-rustfs-svc:9000" (include "posthog.fullname" .) | quote }}
{{- else }}
  value: {{ .Values.externalObjectStorage.endpoint | quote }}
{{- end }}
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
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "OBJECT_STORAGE_PUBLIC_ENDPOINT") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "OBJECT_STORAGE_PUBLIC_ENDPOINT") }}
{{- else }}
- name: OBJECT_STORAGE_PUBLIC_ENDPOINT
  value: {{ printf "https://%s" .Values.ingress.hostname | quote }}
{{- end }}
- name: OBJECT_STORAGE_REGION
  value: "auto"
- name: OBJECT_STORAGE_FORCE_PATH_STYLE
  value: "true"
- name: SESSION_RECORDING_V2_S3_ENDPOINT
{{- if .Values.rustfs.enabled }}
  value: {{ printf "http://%s-rustfs-svc:9000" (include "posthog.fullname" .) | quote }}
{{- else }}
  value: {{ .Values.externalSeaweedfs.endpoint | quote }}
{{- end }}
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
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "CYCLOTRON_DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "CYCLOTRON_DATABASE_URL") }}
{{- else }}
- name: CYCLOTRON_DATABASE_URL
  value: {{ printf "postgres://%s:%s@%s-postgresql:5432/cyclotron" .Values.postgresql.auth.username .Values.postgresql.auth.password (include "posthog.fullname" .) | quote }}
{{- end }}
{{- else if .Values.externalPostgresql.cyclotronUrl }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "CYCLOTRON_DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "CYCLOTRON_DATABASE_URL") }}
{{- else }}
- name: CYCLOTRON_DATABASE_URL
  value: {{ .Values.externalPostgresql.cyclotronUrl | quote }}
{{- end }}
{{- else if include "posthog.externalPostgresqlUseCredentialSecret" . }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "CYCLOTRON_DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "CYCLOTRON_DATABASE_URL") }}
{{- else }}
- name: CYCLOTRON_DATABASE_URL
  value: {{ include "posthog.externalPostgresqlUrlValue" (dict "root" . "database" (.Values.externalPostgresql.cyclotronDatabase | default "cyclotron")) | quote }}
{{- end }}
{{- else if .Values.externalPostgresql.secretName }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "CYCLOTRON_DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "CYCLOTRON_DATABASE_URL") }}
{{- else }}
- name: CYCLOTRON_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalPostgresql.secretName | quote }}
      key: {{ .Values.externalPostgresql.cyclotronUriKey | default "cyclotron-uri" | quote }}
{{- end }}
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
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "CYCLOTRON_DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "CYCLOTRON_DATABASE_URL") }}
{{- else }}
- name: CYCLOTRON_DATABASE_URL
  value: {{ printf "postgres://$(_CNPG_USER):$(_CNPG_PASS)@%s-rw:5432/cyclotron" (include "posthog.fullname" .) | quote }}
{{- end }}
{{- end }}
{{- if .Values.postgresql.enabled }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "PERSONS_DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "PERSONS_DATABASE_URL") }}
{{- else }}
- name: PERSONS_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.secretName" . }}
      key: database-url
{{- end }}
{{- else if .Values.externalPostgresql.personsUrl }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "PERSONS_DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "PERSONS_DATABASE_URL") }}
{{- else }}
- name: PERSONS_DATABASE_URL
  value: {{ .Values.externalPostgresql.personsUrl | quote }}
{{- end }}
{{- else if .Values.externalPostgresql.url }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "PERSONS_DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "PERSONS_DATABASE_URL") }}
{{- else }}
- name: PERSONS_DATABASE_URL
  value: {{ .Values.externalPostgresql.url | quote }}
{{- end }}
{{- else if include "posthog.externalPostgresqlUseCredentialSecret" . }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "PERSONS_DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "PERSONS_DATABASE_URL") }}
{{- else }}
- name: PERSONS_DATABASE_URL
  value: {{ include "posthog.externalPostgresqlUrlValue" (dict "root" . "database" (.Values.externalPostgresql.personsDatabase | default .Values.externalPostgresql.database | default "posthog")) | quote }}
{{- end }}
{{- else if .Values.externalPostgresql.secretName }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "PERSONS_DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "PERSONS_DATABASE_URL") }}
{{- else }}
- name: PERSONS_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.externalPostgresql.secretName | quote }}
      key: {{ .Values.externalPostgresql.personsUriKey | default "persons-uri" | quote }}
{{- end }}
{{- else }}
{{- if include "posthog.hasEnvOverride" (dict "root" . "name" "PERSONS_DATABASE_URL") }}
{{ include "posthog.renderEnvOverride" (dict "root" . "name" "PERSONS_DATABASE_URL") }}
{{- else }}
- name: PERSONS_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "posthog.fullname" . }}-app
      key: uri
{{- end }}
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
{{ include "posthog.renderRemainingCustomEnv" (dict "root" . "excluded" $overridableEnvNames) }}
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
GeoIP init container - downloads MMDB from the central geoip service.
Call with dict "root" .
*/}}
{{- define "posthog.geoipInitContainer" -}}
- name: download-geoip
  image: busybox
  command: ["wget", "-O", "/share/{{ .root.Values.geoip.filename }}", "http://{{ include "posthog.fullname" .root }}-geoip:8080/{{ .root.Values.geoip.filename }}"]
  volumeMounts:
    - name: geoip-db
      mountPath: /share
{{- end }}

{{/*
GeoIP volume mount entry for an application container.
Call with dict "root" .
*/}}
{{- define "posthog.geoipVolumeMount" -}}
- name: geoip-db
  mountPath: /share
  readOnly: true
{{- end }}

{{/*
GeoIP emptyDir volume for a pod spec.
Call with dict "root" .
*/}}
{{- define "posthog.geoipVolume" -}}
- name: geoip-db
  emptyDir: {}
{{- end }}

{{/*
Env vars that point PostHog services at the downloaded MMDB file.
Set explicitly so the path isn't dependent on container WORKDIR or upstream
defaults — both Node.js (MMDB_FILE_LOCATION) and Rust (MAXMIND_DB_PATH) are
included since the helper is used across both service types.
Call with dict "root" .
*/}}
{{- define "posthog.geoipEnv" -}}
- name: MMDB_FILE_LOCATION
  value: /share/{{ .root.Values.geoip.filename }}
- name: MAXMIND_DB_PATH
  value: /share/{{ .root.Values.geoip.filename }}
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
