import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "torn_war_manager.db"

DEFAULT_RANK_PAY_RATES = [
    ("Leader", 0.0),
    ("Kingpin", 110.0),
    ("Co-Leader", 100.0),
    ("Chief Evasion Officer", 100.0),
    ("Ledger Keeper", 100.0),
    ("Failed Audit", 85.0),
    ("Petty Launderer", 85.0),
    ("Audit Bait", 70.0),
]

# (item_id, item_name, armory_category, torn_item_category, default_target_qty)
DEFAULT_ARMORY_TARGETS = [
    (206, "Xanax", "drugs", "Drug", 200),
    (66, "Morphine", "medical", "Medical", 250),
    (67, "First Aid Kit", "medical", "Medical", 250),
    (731, "Empty Blood Bag", "medical", "Medical", 100),
    (732, "Blood Bag - A+", "medical", "Medical", 100),
    (733, "Blood Bag - A-", "medical", "Medical", 100),
    (734, "Blood Bag - B+", "medical", "Medical", 100),
    (735, "Blood Bag - B-", "medical", "Medical", 100),
    (736, "Blood Bag - AB+", "medical", "Medical", 100),
    (737, "Blood Bag - AB-", "medical", "Medical", 100),
    (738, "Blood Bag - O+", "medical", "Medical", 100),
    (739, "Blood Bag - O-", "medical", "Medical", 100),
    (1363, "Ipecac Syrup", "medical", "Medical", 100),
    (242, "High Explosive Grenade", "temporary", "Temporary", 150),
    (222, "Flash Grenade", "temporary", "Temporary", 150),
    (392, "Pepper Spray", "temporary", "Temporary", 150),
    (226, "Smoke Grenade", "temporary", "Temporary", 50),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS rank_pay_rates (
    rank_name TEXT PRIMARY KEY,
    pay_rate_pct REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS armory_targets (
    item_id INTEGER PRIMARY KEY,
    item_name TEXT NOT NULL,
    armory_category TEXT NOT NULL,
    torn_item_category TEXT NOT NULL,
    target_qty INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS wars (
    id INTEGER PRIMARY KEY,
    opponent_name TEXT,
    start INTEGER,
    end INTEGER,
    cache_sell_price REAL NOT NULL DEFAULT 0,
    leadership_cut_pct REAL NOT NULL DEFAULT 15.0,
    outside_pay_rate_pct REAL NOT NULL DEFAULT 70.0,
    synced_at INTEGER
);

CREATE TABLE IF NOT EXISTS war_members (
    war_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    position TEXT,
    level INTEGER,
    inside_hits INTEGER NOT NULL DEFAULT 0,
    outside_hits INTEGER NOT NULL DEFAULT 0,
    assist_hits INTEGER NOT NULL DEFAULT 0,
    respect REAL NOT NULL DEFAULT 0,
    pay_rank TEXT,
    xanax_used INTEGER NOT NULL DEFAULT 0,
    fine_waived INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (war_id, member_id)
);

CREATE TABLE IF NOT EXISTS expense_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    war_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn, name: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
    return row is not None


def _pre_migrate(conn) -> bool:
    """Renames the old war_members table away if it still has the legacy `fine` column
    (replaced by a computed fine + `fine_waived`), so the fresh CREATE TABLE below can run."""
    if not _table_exists(conn, "war_members"):
        return False
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(war_members)")}
    if "fine" not in columns:
        return False
    conn.execute("ALTER TABLE war_members RENAME TO war_members_legacy")
    return True


def _post_migrate(conn, had_legacy_fine: bool):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(war_members)")}
    if "xanax_used" not in columns:
        conn.execute("ALTER TABLE war_members ADD COLUMN xanax_used INTEGER NOT NULL DEFAULT 0")

    if had_legacy_fine:
        conn.execute(
            """
            INSERT INTO war_members
                (war_id, member_id, name, position, level, inside_hits, outside_hits, assist_hits, respect, pay_rank, xanax_used, fine_waived)
            SELECT war_id, member_id, name, position, level, inside_hits, outside_hits, assist_hits, respect, pay_rank, xanax_used, 0
            FROM war_members_legacy
            """
        )
        conn.execute("DROP TABLE war_members_legacy")


def init_db():
    conn = get_connection()
    try:
        had_legacy_fine = _pre_migrate(conn)
        conn.executescript(SCHEMA)
        _post_migrate(conn, had_legacy_fine)

        existing = conn.execute("SELECT COUNT(*) FROM rank_pay_rates").fetchone()[0]
        if existing == 0:
            conn.executemany(
                "INSERT INTO rank_pay_rates (rank_name, pay_rate_pct) VALUES (?, ?)",
                DEFAULT_RANK_PAY_RATES,
            )
        else:
            # Added after the initial seed - make sure it exists on dbs created before this.
            conn.execute(
                "INSERT OR IGNORE INTO rank_pay_rates (rank_name, pay_rate_pct) VALUES ('Kingpin', 110.0)"
            )

        existing = conn.execute("SELECT COUNT(*) FROM armory_targets").fetchone()[0]
        if existing == 0:
            conn.executemany(
                "INSERT INTO armory_targets (item_id, item_name, armory_category, torn_item_category, target_qty) "
                "VALUES (?, ?, ?, ?, ?)",
                DEFAULT_ARMORY_TARGETS,
            )

        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default=None):
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key: str, value: str):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def get_api_key() -> str | None:
    return get_setting("api_key")


def get_faction_id() -> int | None:
    value = get_setting("faction_id")
    return int(value) if value else None
