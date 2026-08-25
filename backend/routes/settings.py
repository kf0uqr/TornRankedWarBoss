from fastapi import APIRouter
from pydantic import BaseModel

from backend import db

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsIn(BaseModel):
    api_key: str | None = None
    faction_id: int | None = None


class RankPayRateIn(BaseModel):
    rank_name: str
    pay_rate_pct: float


@router.get("")
def get_settings():
    return {
        "has_api_key": bool(db.get_api_key()),
        "faction_id": db.get_faction_id(),
    }


@router.post("")
def update_settings(body: SettingsIn):
    if body.api_key:
        db.set_setting("api_key", body.api_key)
    if body.faction_id is not None:
        db.set_setting("faction_id", str(body.faction_id))
    return get_settings()


@router.get("/rank-pay-rates")
def list_rank_pay_rates():
    conn = db.get_connection()
    try:
        rows = conn.execute("SELECT rank_name, pay_rate_pct FROM rank_pay_rates ORDER BY pay_rate_pct DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/rank-pay-rates")
def upsert_rank_pay_rate(body: RankPayRateIn):
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO rank_pay_rates (rank_name, pay_rate_pct) VALUES (?, ?) "
            "ON CONFLICT(rank_name) DO UPDATE SET pay_rate_pct = excluded.pay_rate_pct",
            (body.rank_name, body.pay_rate_pct),
        )
        conn.commit()
    finally:
        conn.close()
    return list_rank_pay_rates()


@router.delete("/rank-pay-rates/{rank_name}")
def delete_rank_pay_rate(rank_name: str):
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM rank_pay_rates WHERE rank_name = ?", (rank_name,))
        conn.commit()
    finally:
        conn.close()
    return list_rank_pay_rates()
