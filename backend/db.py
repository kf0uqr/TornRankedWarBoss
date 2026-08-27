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
    torn_player_id INTEGER,
    is_leadership INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS travel_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    member_name TEXT,
    destination TEXT NOT NULL,
    has_private_island INTEGER NOT NULL DEFAULT 0,
    takeoff_at INTEGER NOT NULL,
    landing_at INTEGER NOT NULL,
    duration_seconds INTEGER NOT NULL,
    recorded_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    member_name TEXT,
    hour_of_day INTEGER NOT NULL,
    is_active INTEGER NOT NULL,
    observed_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_activity_member_hour ON activity_observations(member_id, hour_of_day);

CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    message_id TEXT,
    name TEXT NOT NULL DEFAULT '',
    description TEXT,
    item TEXT NOT NULL,
    num_winners INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,
    created_by TEXT,
    created_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS giveaway_entries (
    giveaway_id INTEGER NOT NULL,
    discord_user_id TEXT NOT NULL,
    entered_at INTEGER NOT NULL,
    PRIMARY KEY (giveaway_id, discord_user_id)
);

CREATE TABLE IF NOT EXISTS giveaway_winners (
    giveaway_id INTEGER NOT NULL,
    discord_user_id TEXT NOT NULL,
    PRIMARY KEY (giveaway_id, discord_user_id)
);

CREATE TABLE IF NOT EXISTS stat_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    member_name TEXT,
    battle_stats_total INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL,
    recorded_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stat_snapshots_member_date ON stat_snapshots(member_id, snapshot_date);
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

    allowed_user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(discord_allowed_users)")}
    if "torn_player_id" not in allowed_user_columns:
        conn.execute("ALTER TABLE discord_allowed_users ADD COLUMN torn_player_id INTEGER")
    if "is_leadership" not in allowed_user_columns:
        # Grandfather in everyone already on the list as leadership - they
        # had full access before this distinction existed, so this preserves
        # that rather than silently locking anyone out.
        conn.execute("ALTER TABLE discord_allowed_users ADD COLUMN is_leadership INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE discord_allowed_users SET is_leadership = 1")

    if _table_exists(conn, "giveaways"):
        giveaway_columns = {row["name"] for row in conn.execute("PRAGMA table_info(giveaways)")}
        if "name" not in giveaway_columns:
            conn.execute("ALTER TABLE giveaways ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        if "description" not in giveaway_columns:
            conn.execute("ALTER TABLE giveaways ADD COLUMN description TEXT")

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


def get_ffscouter_api_key() -> str | None:
    return get_setting("ffscouter_api_key")


def set_ffscouter_api_key(key: str) -> None:
    set_setting("ffscouter_api_key", key)


def list_discord_allowed_users() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, discord_user_id, label, torn_player_id, is_leadership, added_at "
            "FROM discord_allowed_users ORDER BY id"
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


def get_discord_leadership_user_ids() -> set[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT discord_user_id FROM discord_allowed_users WHERE is_leadership = 1"
        ).fetchall()
        return {r["discord_user_id"] for r in rows}
    finally:
        conn.close()


def get_torn_id_to_discord_id_map() -> dict[int, str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT discord_user_id, torn_player_id FROM discord_allowed_users WHERE torn_player_id IS NOT NULL"
        ).fetchall()
        return {r["torn_player_id"]: r["discord_user_id"] for r in rows}
    finally:
        conn.close()


def add_discord_allowed_user(
    discord_user_id: str,
    label: str | None,
    torn_player_id: int | None = None,
    is_leadership: bool = False,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO discord_allowed_users (discord_user_id, label, torn_player_id, is_leadership, added_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(discord_user_id) DO UPDATE SET
                label = excluded.label,
                torn_player_id = excluded.torn_player_id,
                is_leadership = excluded.is_leadership
            """,
            (discord_user_id, label, torn_player_id, 1 if is_leadership else 0, int(time.time())),
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


def add_travel_observation(
    member_id: int,
    member_name: str | None,
    destination: str,
    has_private_island: bool,
    takeoff_at: int,
    landing_at: int,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO travel_observations
                (member_id, member_name, destination, has_private_island, takeoff_at, landing_at, duration_seconds, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                member_id,
                member_name,
                destination,
                1 if has_private_island else 0,
                takeoff_at,
                landing_at,
                landing_at - takeoff_at,
                int(time.time()),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_travel_observations(limit: int = 200) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM travel_observations ORDER BY recorded_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_travel_estimates() -> dict[str, dict]:
    """Observed avg duration (minutes) + sample count per destination, split
    by Private Island status - raw aggregates only, no minimum-sample
    filtering (that's the bot's call, since it's the one deciding whether to
    trust these over its hardcoded standard-time table)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT destination, has_private_island,
                   AVG(duration_seconds) / 60.0 AS avg_minutes,
                   COUNT(*) AS sample_count
            FROM travel_observations
            GROUP BY destination, has_private_island
            """
        ).fetchall()
    finally:
        conn.close()

    estimates: dict[str, dict] = {}
    for r in rows:
        entry = estimates.setdefault(r["destination"], {})
        key = "private_island" if r["has_private_island"] else "standard"
        entry[key] = {"avg_minutes": r["avg_minutes"], "sample_count": r["sample_count"]}
    return estimates


def add_activity_observations(observations: list[dict]) -> None:
    if not observations:
        return
    conn = get_connection()
    try:
        conn.executemany(
            """
            INSERT INTO activity_observations (member_id, member_name, hour_of_day, is_active, observed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (o["member_id"], o.get("member_name"), o["hour_of_day"], 1 if o["is_active"] else 0, o["observed_at"])
                for o in observations
            ],
        )
        conn.commit()
    finally:
        conn.close()


def get_activity_estimates() -> dict[str, dict[str, dict]]:
    """Percent of observed polls where each member was active, bucketed by
    hour of day (0-23, UTC - same as Torn's own clock). Keyed by string
    member_id/hour since this goes straight out as JSON."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT member_id, hour_of_day,
                   SUM(is_active) AS active_count,
                   COUNT(*) AS total_count
            FROM activity_observations
            GROUP BY member_id, hour_of_day
            """
        ).fetchall()
    finally:
        conn.close()

    estimates: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_hour = estimates.setdefault(str(r["member_id"]), {})
        pct = (r["active_count"] / r["total_count"] * 100) if r["total_count"] else None
        by_hour[str(r["hour_of_day"])] = {
            "active_count": r["active_count"],
            "total_count": r["total_count"],
            "pct": pct,
        }
    return estimates


def create_giveaway(
    channel_id: str,
    name: str,
    description: str | None,
    item: str,
    num_winners: int,
    ends_at: int,
    created_by: str | None,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO giveaways
                (channel_id, name, description, item, num_winners, ends_at, created_by, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (channel_id, name, description, item, num_winners, ends_at, created_by, int(time.time())),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def set_giveaway_message_id(giveaway_id: int, message_id: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE giveaways SET message_id = ? WHERE id = ?", (message_id, giveaway_id))
        conn.commit()
    finally:
        conn.close()


def get_giveaway(giveaway_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_active_giveaways() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM giveaways WHERE status = 'active'").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_giveaway_entry(giveaway_id: int, discord_user_id: str) -> bool:
    """Returns True if this was a new entry, False if they'd already entered."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO giveaway_entries (giveaway_id, discord_user_id, entered_at) VALUES (?, ?, ?)",
            (giveaway_id, discord_user_id, int(time.time())),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def count_giveaway_entries(giveaway_id: int) -> int:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def list_giveaway_entries(giveaway_id: int) -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT discord_user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
        ).fetchall()
        return [r["discord_user_id"] for r in rows]
    finally:
        conn.close()


def finalize_giveaway(giveaway_id: int, winner_discord_user_ids: list[str]) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE giveaways SET status = 'ended' WHERE id = ?", (giveaway_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO giveaway_winners (giveaway_id, discord_user_id) VALUES (?, ?)",
            [(giveaway_id, uid) for uid in winner_discord_user_ids],
        )
        conn.commit()
    finally:
        conn.close()


def cancel_giveaway(giveaway_id: int) -> None:
    """Distinct status from 'ended' (a completed draw) so a cancelled
    giveaway's history isn't mistaken for one that ran to completion."""
    conn = get_connection()
    try:
        conn.execute("UPDATE giveaways SET status = 'cancelled' WHERE id = ?", (giveaway_id,))
        conn.commit()
    finally:
        conn.close()


def has_stat_snapshot_today(snapshot_date: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM stat_snapshots WHERE snapshot_date = ? LIMIT 1", (snapshot_date,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def add_stat_snapshots(snapshot_date: str, entries: list[dict]) -> None:
    """entries: [{"member_id", "member_name", "battle_stats_total"}, ...]"""
    if not entries:
        return
    conn = get_connection()
    try:
        now = int(time.time())
        conn.executemany(
            """
            INSERT INTO stat_snapshots (member_id, member_name, battle_stats_total, snapshot_date, recorded_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(e["member_id"], e["member_name"], e["battle_stats_total"], snapshot_date, now) for e in entries],
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_stat_snapshots() -> list[dict]:
    """Most recent snapshot per member, regardless of when - the "now" side
    of a gains comparison, even if today's capture hasn't run yet."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT s.member_id, s.member_name, s.battle_stats_total, s.recorded_at
            FROM stat_snapshots s
            INNER JOIN (
                SELECT member_id, MAX(recorded_at) AS max_recorded_at
                FROM stat_snapshots
                GROUP BY member_id
            ) latest ON s.member_id = latest.member_id AND s.recorded_at = latest.max_recorded_at
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_earliest_stat_snapshots_since(since_ts: int) -> list[dict]:
    """Earliest snapshot per member at-or-after since_ts - the "baseline"
    side of a gains comparison."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT s.member_id, s.member_name, s.battle_stats_total, s.recorded_at
            FROM stat_snapshots s
            INNER JOIN (
                SELECT member_id, MIN(recorded_at) AS min_recorded_at
                FROM stat_snapshots
                WHERE recorded_at >= ?
                GROUP BY member_id
            ) earliest ON s.member_id = earliest.member_id AND s.recorded_at = earliest.min_recorded_at
            """,
            (since_ts,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
