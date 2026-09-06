"""M12: Edge Gateway service entrypoint (deployment artifact).

Runs the Edge runtime over a durable SQLite store. Not started automatically.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from parking.edge.runtime import EdgeRuntime
from parking.edge.store import EdgeStore


def main() -> None:
    parser = argparse.ArgumentParser(description="BotConnector Parking Edge Gateway")
    parser.add_argument("--data-dir", default=os.environ.get("PARKING_EDGE_DATA_DIR", "/var/lib/botconnector-parking-edge"))
    parser.add_argument("--edge-id", default=os.environ.get("PARKING_EDGE_ID", "edge-1"))
    parser.add_argument("--tenant-id", type=int, default=int(os.environ.get("PARKING_EDGE_TENANT_ID", "1")))
    parser.add_argument("--site-id", type=int, default=int(os.environ.get("PARKING_EDGE_SITE_ID", "1")))
    parser.add_argument("--health", action="store_true", help="print health and exit")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    store = EdgeStore(str(data_dir / "edge.db"))
    store.set_identity(edge_id=args.edge_id, tenant_id=args.tenant_id, site_id=args.site_id)
    edge = EdgeRuntime(store)

    if args.health:
        import json
        print(json.dumps(edge.health(), indent=2))
        store.close()
        return

    # In a real deployment this would run a sync loop. For M12 it is a
    # deployable entrypoint; the deterministic simulator covers behavior.
    print(f"Edge {args.edge_id} running (site {args.site_id}). Data: {data_dir}")
    store.close()


if __name__ == "__main__":
    main()
