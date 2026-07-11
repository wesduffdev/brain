"""Kafka topic bootstrap — provision the being.* topics + their DLQ companions.

This is the topic-bootstrap step the EVT-KAFKA slice promises: it reads the topic
topology from config (`ConfigService.event_topics_policy` -> `config/events.yaml`)
and the broker URL from the environment (`KAFKA_BOOTSTRAP_SERVERS`), then creates
every topic in `bootstrap_topics()` — each being.* topic followed by its `.dlq`
companion — at the configured partition count. Config is the single source of
truth for topic names; this module never spells one out.

It is **idempotent**: a topic that already exists is left as-is (so re-running
`make kafka-up` is safe), and it fails clearly only on a genuine broker error.

Run it against the configured broker with::

    python -m app.kafka_bootstrap        # uses KAFKA_BOOTSTRAP_SERVERS + CONFIG_ROOT

`confluent_kafka` is imported lazily inside `main`, matching the adapter, so the
module imports with no C extension present.
"""
from __future__ import annotations

import os

from app.adapters.kafka_event_bus import bootstrap_servers_from_env
from app.config_service import ConfigService
from app.policies import EventTopicsPolicy

_DEFAULT_CONFIG_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def create_topics(bootstrap_servers: str, topics: EventTopicsPolicy) -> None:
    """Create every `bootstrap_topics()` topic at the policy's partition count,
    replication factor 1 (single broker, single being). Existing topics are left
    untouched; any other creation error is raised."""
    from confluent_kafka.admin import AdminClient, NewTopic  # noqa: PLC0415

    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    new_topics = [
        NewTopic(name, num_partitions=topics.partitions, replication_factor=1)
        for name in topics.bootstrap_topics()
    ]
    results = admin.create_topics(new_topics)
    for name, future in results.items():
        try:
            future.result()  # block until the create completes
            print(f"created topic {name} (partitions={topics.partitions})")
        except Exception as exc:  # noqa: BLE001
            # confluent raises KafkaException wrapping a TOPIC_ALREADY_EXISTS error
            # when the topic is already there — that is success for an idempotent
            # bootstrap; anything else is a real failure.
            if "TOPIC_ALREADY_EXISTS" in str(exc) or "already exists" in str(exc):
                print(f"topic {name} already exists — leaving as-is")
            else:
                raise


def main() -> None:
    config_root = os.environ.get("CONFIG_ROOT", _DEFAULT_CONFIG_ROOT)
    bootstrap = bootstrap_servers_from_env()
    topics = ConfigService.from_files(config_root).event_topics_policy()
    print(f"provisioning {len(topics.bootstrap_topics())} topics on {bootstrap}...")
    create_topics(bootstrap, topics)
    print("kafka topic bootstrap complete")


if __name__ == "__main__":
    main()
