import os
from typing import Any

# GraphDatabase is optional - may not be installed
GraphDatabase: Any | None = None

try:
    from neo4j import GraphDatabase  # noqa: F811
except ImportError:
    pass  # GraphDatabase stays None


def bootstrap() -> None:
    if GraphDatabase is None:
        print("[memgraph] neo4j driver not available; skipping bootstrap")
        return

    uri = os.getenv("MEMGRAPH_URI") or os.getenv("NEO4J_URI")
    if not uri:
        print("[memgraph] MEMGRAPH_URI not set; skipping bootstrap")
        return

    user = os.getenv("MEMGRAPH_USER") or os.getenv("NEO4J_USER")
    password = os.getenv("MEMGRAPH_PASSWORD") or os.getenv("NEO4J_PASSWORD")
    # Only create auth tuple if both user and password are present
    auth: tuple[str, str] | None = None
    if user and password:
        auth = (user, password)

    driver = GraphDatabase.driver(uri, auth=auth)

    def _create(tx):
        tx.run(
            "CREATE INDEX entity_type_id IF NOT EXISTS FOR (e:Entity) ON (e.type, e.id)"
        )

    with driver.session() as session:
        session.execute_write(_create)

    driver.close()


if __name__ == "__main__":
    bootstrap()
