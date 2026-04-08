FROM clickhouse/clickhouse-server:25.9.7

# PostHog UDF scripts (Python-based aggregate funnels, etc.)
COPY --chmod=755 vendor/posthog/user_scripts/ /var/lib/clickhouse/user_scripts/
COPY vendor/posthog/user_scripts/latest_user_defined_function.xml /etc/clickhouse-server/user_defined_function.xml

# PostHog server tuning and profile settings (config.d/ overlay — merges with
# the base image config; deployment-specific settings like cluster topology,
# ZooKeeper, and Kafka brokers are mounted via ConfigMap at runtime).
COPY images/clickhouse/posthog-config.xml /etc/clickhouse-server/config.d/posthog.xml
COPY images/clickhouse/posthog-users.xml  /etc/clickhouse-server/users.d/posthog.xml
