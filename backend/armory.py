"""Armory restock calculator - generalized version of the old test.py script.

Target quantities are stored in the DB and user-editable (instead of hardcoded),
on-hand quantities and prices are pulled live from Torn.
"""

import re

from backend import db
from backend.torn_api import TornClient

# Faction news doesn't expose structured item-use events, only free text like:
#   <a href="https://www.torn.com/profiles.php?XID=123456">PlayerName</a> used one of the faction's Xanax items.
_ANCHOR_RE = re.compile(r"XID=(\d+)[^>]*>([^<]*)</a>")
_USED_RE = re.compile(r"used one of the faction's\s+(.+?)\s+items?\b", re.IGNORECASE)


def count_item_usage(client: TornClient, item_name: str, from_ts: int, to_ts: int) -> dict[int, int]:
    """Counts how many times each member used `item_name` from the faction armory in [from_ts, to_ts]."""
    target = item_name.strip().lower()
    counts: dict[int, int] = {}
    for entry in client.faction_news("armoryAction", from_ts, to_ts):
        text = entry.get("text", "")
        used_match = _USED_RE.search(text)
        if not used_match or used_match.group(1).strip().lower() != target:
            continue
        anchor_match = _ANCHOR_RE.search(text)
        if not anchor_match:
            continue
        member_id = int(anchor_match.group(1))
        counts[member_id] = counts.get(member_id, 0) + 1
    return counts


def get_armory_targets(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT item_id, item_name, armory_category, torn_item_category, target_qty, include_display_case "
        "FROM armory_targets ORDER BY armory_category, item_name"
    ).fetchall()
    return [dict(row) for row in rows]


def set_armory_target(conn, item_id: int, target_qty: int):
    conn.execute(
        "UPDATE armory_targets SET target_qty = ? WHERE item_id = ?",
        (target_qty, item_id),
    )
    conn.commit()


def set_armory_include_display_case(conn, item_id: int, include_display_case: bool):
    conn.execute(
        "UPDATE armory_targets SET include_display_case = ? WHERE item_id = ?",
        (1 if include_display_case else 0, item_id),
    )
    conn.commit()


def add_armory_target(conn, item_id: int, item_name: str, armory_category: str, torn_item_category: str, target_qty: int):
    conn.execute(
        "INSERT OR REPLACE INTO armory_targets "
        "(item_id, item_name, armory_category, torn_item_category, target_qty) VALUES (?, ?, ?, ?, ?)",
        (item_id, item_name, armory_category, torn_item_category, target_qty),
    )
    conn.commit()


def remove_armory_target(conn, item_id: int):
    conn.execute("DELETE FROM armory_targets WHERE item_id = ?", (item_id,))
    conn.commit()


def get_display_case_quantities() -> dict[int, int]:
    """Whatever's sitting in the display case of the pool's primary key
    holder right now, keyed by item id. /user?selections=display is a
    personal endpoint - Torn only ever returns the calling key's own
    account's display case, never an arbitrary target - so this always uses
    db.get_primary_api_key() specifically, never the round-robined pool."""
    key = db.get_primary_api_key()
    if not key:
        return {}
    quantities: dict[int, int] = {}
    for entry in TornClient([key]).user_display_case():
        quantities[entry["ID"]] = quantities.get(entry["ID"], 0) + entry["quantity"]
    return quantities


def compute_restock(client: TornClient, targets: list[dict]) -> dict:
    armory_categories = {t["armory_category"] for t in targets}
    torn_categories = {t["torn_item_category"] for t in targets}

    on_hand_by_id: dict[int, int] = {}
    for cat in armory_categories:
        for entry in client.faction_inventory(cat):
            on_hand_by_id[entry["id"]] = entry["amount"]

    price_by_id: dict[int, float] = {}
    for cat in torn_categories:
        for entry in client.torn_items(cat):
            price_by_id[entry["id"]] = entry["value"]["market_price"]

    # Only fetched if something actually needs it - most factions don't
    # round-trip any item through a personal display case at all.
    display_case_by_id: dict[int, int] = {}
    if any(t.get("include_display_case") for t in targets):
        display_case_by_id = get_display_case_quantities()

    lines = []
    total_cost = 0.0
    for t in targets:
        item_id = t["item_id"]
        # Armory stock and display-case stock are mutually exclusive at any
        # given moment (an item is physically in one or the other) but which
        # one holds it flips around a war, so summing both is always correct
        # regardless of which state things are currently in - no need to
        # special-case "is a war active right now".
        on_hand = on_hand_by_id.get(item_id, 0)
        if t.get("include_display_case"):
            on_hand += display_case_by_id.get(item_id, 0)
        needed = max(0, t["target_qty"] - on_hand)
        unit_price = price_by_id.get(item_id, 0)
        cost = needed * unit_price
        total_cost += cost
        lines.append(
            {
                "item_id": item_id,
                "item_name": t["item_name"],
                "target_qty": t["target_qty"],
                "on_hand": on_hand,
                "include_display_case": bool(t.get("include_display_case")),
                "needed": needed,
                "unit_price": unit_price,
                "cost": cost,
            }
        )

    return {"lines": lines, "total_cost": total_cost}
