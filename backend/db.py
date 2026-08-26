import sqlite3
import time
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

CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT NOT NULL UNIQUE,
    label TEXT,
    added_at INTEGER
);

CREATE TABLE IF NOT EXISTS discord_allowed_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_user_id TEXT NOT NULL UNIQUE,
    label TEXT,
    added_at INTEGER
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
    is_termed INTEGER NOT NULL DEFAULT 0,
    termed_at INTEGER,
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
    respect_lost REAL NOT NULL DEFAULT 0,
    pay_rank TEXT,
    xanax_used INTEGER NOT NULL DEFAULT 0,
    fine_waived INTEGER NOT NULL DEFAULT 0,
    paid INTEGER NOT NULL DEFAULT 0,
    best_hit REAL NOT NULL DEFAULT 0,
    chain_respect_total REAL NOT NULL DEFAULT 0,
    chain_hits_total INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    escapes INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    retaliation_hits INTEGER NOT NULL DEFAULT 0,
    bonus_hits INTEGER NOT NULL DEFAULT 0,
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
    if "respect_lost" not in columns:
        conn.execute("ALTER TABLE war_members ADD COLUMN respect_lost REAL NOT NULL DEFAULT 0")
    if "paid" not in columns:
        conn.execute("ALTER TABLE war_members ADD COLUMN paid INTEGER NOT NULL DEFAULT 0")
    for col, ddl in (
        ("best_hit", "REAL NOT NULL DEFAULT 0"),
        ("chain_respect_total", "REAL NOT NULL DEFAULT 0"),
        ("chain_hits_total", "INTEGER NOT NULL DEFAULT 0"),
        ("losses", "INTEGER NOT NULL DEFAULT 0"),
        ("escapes", "INTEGER NOT NULL DEFAULT 0"),
        ("draws", "INTEGER NOT NULL DEFAULT 0"),
        ("retaliation_hits", "INTEGER NOT NULL DEFAULT 0"),
        ("bonus_hits", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if col not in columns:
            conn.execute(f"ALTER TABLE war_members ADD COLUMN {col} {ddl}")

    war_columns = {row["name"] for row in conn.execute("PRAGMA table_info(wars)")}
    if "is_termed" not in war_columns:
        conn.execute("ALTER TABLE wars ADD COLUMN is_termed INTEGER NOT NULL DEFAULT 0")
    if "termed_at" not in war_columns:
        conn.execute("ALTER TABLE wars ADD COLUMN termed_at INTEGER")

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


def _migrate_single_api_key(conn):
    """Moves the old single settings.api_key into the api_keys pool, if it's not
    already there - so an existing setup keeps working without re-entering it."""
    existing_key_count = conn.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
    if existing_key_count:
        return
    row = conn.execute("SELECT value FROM settings WHERE key = 'api_key'").fetchone()
    if row and row["value"]:
        conn.execute(
            "INSERT OR IGNORE INTO api_keys (api_key, label, added_at) VALUES (?, ?, ?)",
            (row["value"], "Primary", int(time.time())),
        )


def init_db():
    conn = get_connection()
    try:
        had_legacy_fine = _pre_migrate(conn)
        conn.executescript(SCHEMA)
        _post_migrate(conn, had_legacy_fine)
        _migrate_single_api_key(conn)

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


def get_faction_id() -> int | None:
    value = get_setting("faction_id")
    return int(value) if value else None


def list_api_keys() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, api_key, label, added_at FROM api_keys ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_api_keys() -> list[str]:
    """The raw key strings, for actually calling Torn - use list_api_keys() for display."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT api_key FROM api_keys ORDER BY id").fetchall()
        return [r["api_key"] for r in rows]
    finally:
        conn.close()


def add_api_key(api_key: str, label: str | None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO api_keys (api_key, label, added_at) VALUES (?, ?, ?)",
            (api_key, label, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()


def remove_api_key(key_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        conn.commit()
    finally:
        conn.close()


def get_discord_bot_token() -> str | None:
    return get_setting("discord_bot_token")


def set_discord_bot_token(token: str) -> None:
    set_setting("discord_bot_token", token)


def list_discord_allowed_users() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, discord_user_id, label, added_at FROM discord_allowed_users ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_discord_allowed_user_ids() -> set[str]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT discord_user_id FROM discord_allowed_users").fetchall()
        return {r["discord_user_id"] for r in rows}
    finally:
        conn.close()


def add_discord_allowed_user(discord_user_id: str, label: str | None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO discord_allowed_users (discord_user_id, label, added_at) VALUES (?, ?, ?)",
            (discord_user_id, label, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()


def remove_discord_allowed_user(entry_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM discord_allowed_users WHERE id = ?", (entry_id,))
        conn.commit()
    finally:
        conn.close()
