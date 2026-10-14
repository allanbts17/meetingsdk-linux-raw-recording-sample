"""Container probe: reads durable heartbeat without fetching or printing secrets."""
import os
from pathlib import Path
import sqlite3
import time


def main():
    path = Path(os.environ.get("ZOOM_STATE_ROOT", "/state")) / "state.db"
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            row = db.execute("SELECT updated,ready FROM worker_health WHERE singleton=1").fetchone()
            reconciling = db.execute("SELECT 1 FROM reconciling LIMIT 1").fetchone()
        return 0 if row and row[1] and 0 <= time.time() - row[0] <= 15 and not reconciling else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
