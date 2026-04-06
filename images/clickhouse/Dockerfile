FROM docker.io/apecloud/clickhouse:25.9.7
COPY vendor/posthog/user_scripts/ /var/lib/clickhouse/user_scripts/
RUN find /var/lib/clickhouse/user_scripts -type f ! -name '*.xml' -exec chmod 755 {} +
COPY vendor/posthog/user_scripts/latest_user_defined_function.xml /etc/clickhouse-server/user_defined_function.xml
