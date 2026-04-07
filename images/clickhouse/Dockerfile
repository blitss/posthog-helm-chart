FROM docker.io/apecloud/clickhouse:25.9.7
COPY --chmod=755 vendor/posthog/user_scripts/ /var/lib/clickhouse/user_scripts/
COPY vendor/posthog/user_scripts/latest_user_defined_function.xml /etc/clickhouse-server/user_defined_function.xml
