"""Armory restock calculator - generalized version of the old test.py script.

Target quantities are stored in the DB and user-editable (instead of hardcoded),
on-hand quantities and prices are pulled live from Torn.
"""

import re

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
        "SELECT item_id, item_name, armory_category, torn_item_category, target_qty, manual_adjustment "
        "FROM armory_targets ORDER BY armory_category, item_name"
    ).fetchall()
    return [dict(row) for row in rows]


def set_armory_target(conn, item_id: int, target_qty: int):
    conn.execute(
        "UPDATE armory_targets SET target_qty = ? WHERE item_id = ?",
        (target_qty, item_id),
    )
    conn.commit()


def set_armory_manual_adjustment(conn, item_id: int, manual_adjustment: int):
    """Extra units to fold into an item's on-hand count for restock math -
    for stock Torn's own API can't see (e.g. everything of that item has
    been moved into someone's personal display case, which drops it out of
    /faction/inventory's response entirely) but should still count as
    available, e.g. because it's earmarked to come back to the armory."""
    conn.execute(
        "UPDATE armory_targets SET manual_adjustment = ? WHERE item_id = ?",
        (manual_adjustment, item_id),
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

    lines = []
    total_cost = 0.0
    for t in targets:
        item_id = t["item_id"]
        # manual_adjustment covers stock Torn's own API can't see - e.g. once
        # every unit of an item is moved into someone's personal display
        # case, it drops out of /faction/inventory's response entirely
        # (confirmed against Torn's API directly: the item just isn't in the
        # list, not even at 0) even though it may still be earmarked to come
        # back to the armory later.
        on_hand = on_hand_by_id.get(item_id, 0) + t.get("manual_adjustment", 0)
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
                "manual_adjustment": t.get("manual_adjustment", 0),
                "needed": needed,
                "unit_price": unit_price,
                "cost": cost,
            }
        )

    return {"lines": lines, "total_cost": total_cost}
