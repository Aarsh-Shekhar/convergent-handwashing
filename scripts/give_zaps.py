"""Testing only: add zaps to the parent app so rewards can be tried without washing.

    .venv/bin/python scripts/give_zaps.py 500

Writes one "_gift" row to the backend's database (the same one in .env). It is not a wash, so
history and progress are untouched. "Delete wash history" in the app removes it again.
Reload the app page to see the new balance.
"""

from __future__ import annotations

import argparse

from convergent.backend import models as m
from convergent.backend.database import Database, run_migrations
from convergent.common.config import load_settings
from convergent.common.timestamps import utc_now


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zaps", type=int, nargs="?", default=500)
    n = ap.parse_args().zaps
    url = load_settings().database_url
    run_migrations(url)
    db = Database(url)
    with db.session() as s:
        row = s.get(m.GermUnlock, "_gift")
        if row is None:
            row = m.GermUnlock(germ="_gift", spent=0, how="gift", created_utc=utc_now())
            s.add(row)
        row.spent -= n  # a negative spend adds to the balance
        s.commit()
        print(f"gave {n} test zaps (total gifted: {-row.spent}) in {url}")
    db.dispose()


if __name__ == "__main__":
    main()
