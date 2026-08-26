from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import armory, db, payout, stats, sync
from backend.deps import require_client, require_faction_id, torn_error_to_http
from backend.torn_api import TornAPIError

router = APIRouter(prefix="/api/wars", tags=["wars"])


class WarSettingsIn(BaseModel):
    cache_sell_price: float | None = None
    leadership_cut_pct: float | None = None
    outside_pay_rate_pct: float | None = None
    is_termed: bool | None = None
    termed_at: int | None = None


class ExpenseLineIn(BaseModel):
    label: str
    amount: float


class MemberUpdateIn(BaseModel):
    fine_waived: bool | None = None
    pay_rank: str | None = None
    paid: bool | None = None


@router.get("/available")
def available_wars():
    faction_id = require_faction_id()
    client = require_client()
    try:
        wars = client.faction_rankedwars(faction_id)
    except TornAPIError as exc:
        raise torn_error_to_http(exc)
    finally:
        client.close()

    conn = db.get_connection()
    try:
        synced_ids = {r["id"] for r in conn.execute("SELECT id FROM wars").fetchall()}
    finally:
        conn.close()

    result = []
    for w in wars:
        opponent = next((f["name"] for f in w["factions"] if f["id"] != faction_id), None)
        result.append(
            {
                "id": w["id"],
                "opponent_name": opponent,
                "start": w["start"],
                "end": w["end"],
                "winner": w["winner"],
                "already_synced": w["id"] in synced_ids,
            }
        )
    return result


@router.get("/current")
def current_war():
    """The faction's currently-active ranked war (if any), plus the enemy
    faction's live roster - status/level/last-action, for a war-room view.
    Unlike the rest of this router, this never touches the local DB: it's
    meant to work before a war is synced (or ever synced) into `wars`."""
    faction_id = require_faction_id()
    client = require_client()
    try:
        wars = client.faction_rankedwars(faction_id, limit=5)
        current = next((w for w in wars if w["end"] == 0), None)
        if current is None:
            return {"war": None, "members": []}

        own = next(f for f in current["factions"] if f["id"] == faction_id)
        opponent = next(f for f in current["factions"] if f["id"] != faction_id)
        members = client.faction_members(opponent["id"])
    except TornAPIError as exc:
        raise torn_error_to_http(exc)
    finally:
        client.close()

    return {
        "war": {
            "id": current["id"],
            "start": current["start"],
            "target": current["target"],
            "own_score": own["score"],
            "opponent_id": opponent["id"],
            "opponent_name": opponent["name"],
            "opponent_score": opponent["score"],
        },
        "members": members,
    }


@router.get("")
def list_wars():
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, opponent_name, start, end, cache_sell_price, synced_at FROM wars ORDER BY start DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/{war_id}/sync")
def sync_war(war_id: int):
    faction_id = require_faction_id()
    client = require_client()
    try:
        conn = db.get_connection()
        try:
            sync.sync_war(client, conn, faction_id, war_id)
        finally:
            conn.close()
    except TornAPIError as exc:
        raise torn_error_to_http(exc)
    finally:
        client.close()
    return get_war(war_id)


def _get_war_row(conn, war_id: int):
    row = conn.execute("SELECT * FROM wars WHERE id = ?", (war_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="War not found. Sync it first.")
    return dict(row)


@router.get("/{war_id}")
def get_war(war_id: int):
    conn = db.get_connection()
    try:
        war = _get_war_row(conn, war_id)

        expense_rows = conn.execute(
            "SELECT id, label, amount FROM expense_lines WHERE war_id = ? ORDER BY id", (war_id,)
        ).fetchall()
        expense_lines = [dict(r) for r in expense_rows]

        armory_line = {"id": None, "label": "Armory Restock", "amount": 0.0}
        armory_error = None
        try:
            client = require_client()
            try:
                targets = armory.get_armory_targets(conn)
                restock = armory.compute_restock(client, targets)
                armory_line["amount"] = restock["total_cost"]
                armory_line["detail"] = restock["lines"]
            finally:
                client.close()
        except (HTTPException, TornAPIError) as exc:
            armory_error = getattr(exc, "detail", None) or getattr(exc, "message", str(exc))

        member_rows = conn.execute(
            "SELECT * FROM war_members WHERE war_id = ? ORDER BY name", (war_id,)
        ).fetchall()
        members = [
            payout.MemberInput(
                member_id=r["member_id"],
                name=r["name"],
                inside_hits=r["inside_hits"],
                outside_hits=r["outside_hits"],
                assist_hits=r["assist_hits"],
                xanax_used=r["xanax_used"],
                fine_waived=bool(r["fine_waived"]),
                pay_rank=r["pay_rank"],
            )
            for r in member_rows
        ]

        # Co-Leader / Chief Evasion Officer draw a flat salary on top of hit-based pay
        # (see payout.FLAT_RANK_BONUSES) - it's a real cost, so it goes in expenses too.
        salary_total = sum(payout.FLAT_RANK_BONUSES.get(m.pay_rank, 0.0) for m in members)
        salary_line = {"id": None, "label": "Leadership Salaries (Co-Leader/CEO)", "amount": salary_total}

        all_expense_lines = expense_lines + [armory_line, salary_line]

        rank_rows = conn.execute("SELECT rank_name, pay_rate_pct FROM rank_pay_rates").fetchall()
        rank_pay_rates = {r["rank_name"]: r["pay_rate_pct"] for r in rank_rows}

        result = payout.compute_paysheet(
            cache_sell_price=war["cache_sell_price"],
            expense_lines=all_expense_lines,
            leadership_cut_pct=war["leadership_cut_pct"],
            outside_pay_rate_pct=war["outside_pay_rate_pct"],
            members=members,
            rank_pay_rates=rank_pay_rates,
        )

        member_meta = {r["member_id"]: dict(r) for r in member_rows}

        return {
            "war": war,
            "expense_lines": expense_lines,
            "armory_line": armory_line,
            "armory_error": armory_error,
            "salary_line": salary_line,
            "totals": {
                "total_expenses": result.total_expenses,
                "war_pay": result.war_pay,
                "pay_for_hits": result.pay_for_hits,
                "leadership_cut_amount": result.leadership_cut_amount,
                "total_inside_hits": result.total_inside_hits,
                "total_outside_assist_hits": result.total_outside_assist_hits,
                "per_inside_hit_rate": result.per_inside_hit_rate,
                "per_outside_hit_rate": result.per_outside_hit_rate,
            },
            "members": [
                {
                    **vars(m),
                    "position": member_meta.get(m.member_id, {}).get("position"),
                    "level": member_meta.get(m.member_id, {}).get("level"),
                    "respect": member_meta.get(m.member_id, {}).get("respect"),
                    "paid": bool(member_meta.get(m.member_id, {}).get("paid")),
                }
                for m in result.members
            ],
        }
    finally:
        conn.close()


@router.get("/{war_id}/stats")
def get_war_stats(war_id: int):
    conn = db.get_connection()
    try:
        _get_war_row(conn, war_id)
        member_rows = conn.execute(
            "SELECT member_id, name, inside_hits, outside_hits, assist_hits, respect, respect_lost, pay_rank, "
            "best_hit, chain_respect_total, chain_hits_total, losses, escapes, draws, retaliation_hits, bonus_hits "
            "FROM war_members WHERE war_id = ?",
            (war_id,),
        ).fetchall()
        members = [dict(r) for r in member_rows]
        return stats.compute_player_stats(members)
    finally:
        conn.close()


@router.patch("/{war_id}")
def update_war_settings(war_id: int, body: WarSettingsIn):
    conn = db.get_connection()
    try:
        _get_war_row(conn, war_id)
        sent = body.model_dump(exclude_unset=True)
        fields, values = [], []
        for field in ("cache_sell_price", "leadership_cut_pct", "outside_pay_rate_pct"):
            if sent.get(field) is not None:
                fields.append(f"{field} = ?")
                values.append(sent[field])
        # is_termed/termed_at can be explicitly cleared to null, so check "was it sent"
        # rather than "is it not None" - unlike the numeric settings above.
        if "is_termed" in sent:
            fields.append("is_termed = ?")
            values.append(1 if sent["is_termed"] else 0)
        if "termed_at" in sent:
            fields.append("termed_at = ?")
            values.append(sent["termed_at"])
        if fields:
            values.append(war_id)
            conn.execute(f"UPDATE wars SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()
    finally:
        conn.close()
    return get_war(war_id)


@router.post("/{war_id}/expenses")
def add_expense_line(war_id: int, body: ExpenseLineIn):
    conn = db.get_connection()
    try:
        _get_war_row(conn, war_id)
        conn.execute(
            "INSERT INTO expense_lines (war_id, label, amount) VALUES (?, ?, ?)",
            (war_id, body.label, body.amount),
        )
        conn.commit()
    finally:
        conn.close()
    return get_war(war_id)


@router.patch("/{war_id}/expenses/{line_id}")
def update_expense_line(war_id: int, line_id: int, body: ExpenseLineIn):
    conn = db.get_connection()
    try:
        conn.execute(
            "UPDATE expense_lines SET label = ?, amount = ? WHERE id = ? AND war_id = ?",
            (body.label, body.amount, line_id, war_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_war(war_id)


@router.delete("/{war_id}/expenses/{line_id}")
def delete_expense_line(war_id: int, line_id: int):
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM expense_lines WHERE id = ? AND war_id = ?", (line_id, war_id))
        conn.commit()
    finally:
        conn.close()
    return get_war(war_id)


@router.patch("/{war_id}/members/{member_id}")
def update_member(war_id: int, member_id: int, body: MemberUpdateIn):
    conn = db.get_connection()
    try:
        fields, values = [], []
        if body.fine_waived is not None:
            fields.append("fine_waived = ?")
            values.append(1 if body.fine_waived else 0)
        if body.pay_rank is not None:
            fields.append("pay_rank = ?")
            values.append(body.pay_rank)
        if body.paid is not None:
            fields.append("paid = ?")
            values.append(1 if body.paid else 0)
        if fields:
            values.extend([war_id, member_id])
            conn.execute(
                f"UPDATE war_members SET {', '.join(fields)} WHERE war_id = ? AND member_id = ?", values
            )
            conn.commit()
    finally:
        conn.close()
    return get_war(war_id)
