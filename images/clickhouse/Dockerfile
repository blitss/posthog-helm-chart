FROM clickhouse/clickhouse-server:25.9.7

# PostHog UDF scripts must not live under /var/lib/clickhouse because the data
# volume is mounted there and hides image-baked files at runtime.
COPY --chmod=755 vendor/posthog/user_scripts/ /usr/local/share/posthog/user_scripts/
COPY vendor/posthog/docker/clickhouse/user_defined_function.xml /etc/clickhouse-server/user_defined_function.xml

# PostHog server tuning and profile settings (config.d/ overlay — merges with
# the base image config; deployment-specific settings like cluster topology,
# ZooKeeper, and Kafka brokers are mounted via ConfigMap at runtime).
COPY images/clickhouse/posthog-config.xml /etc/clickhouse-server/config.d/posthog.xml
COPY images/clickhouse/posthog-users.xml  /etc/clickhouse-server/users.d/posthog.xml
