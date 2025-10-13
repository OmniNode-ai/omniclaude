import os

try:
    from neo4j import GraphDatabase  # type: ignore
except Exception:
    GraphDatabase = None  # type: ignore


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
    auth = (user, password) if user or password else None

    driver = GraphDatabase.driver(uri, auth=auth)

    def _create(tx):
        tx.run("CREATE INDEX entity_type_id IF NOT EXISTS FOR (e:Entity) ON (e.type, e.id)")

    with driver.session() as session:
        session.execute_write(_create)

    driver.close()


if __name__ == "__main__":
    bootstrap()


