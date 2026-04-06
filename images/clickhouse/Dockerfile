FROM docker.io/posthog/posthog:latest AS posthog
FROM docker.io/apecloud/clickhouse:25.9.7
COPY --from=posthog --chmod=755 /code/posthog/user_scripts/ /var/lib/clickhouse/user_scripts/
COPY --from=posthog /code/docker/clickhouse/user_defined_function.xml /etc/clickhouse-server/user_defined_function.xml
