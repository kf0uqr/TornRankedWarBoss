import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import db
from backend.torn_api import TornAPIError, TornClient

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsIn(BaseModel):
    faction_id: int | None = None


class RankPayRateIn(BaseModel):
    rank_name: str
    pay_rate_pct: float


class ApiKeyIn(BaseModel):
    api_key: str
    label: str | None = None


class ValidatedApiKeyIn(BaseModel):
    api_key: str
    label: str | None = None


class DiscordBotTokenIn(BaseModel):
    token: str


class DiscordGuildIdIn(BaseModel):
    guild_id: str


class DiscordAllowedUserIn(BaseModel):
    discord_user_id: str
    label: str | None = None
    torn_player_id: int | None = None
    is_leadership: bool = False


class DiscordAlertChannelIdIn(BaseModel):
    channel_id: str


class DiscordWarStatusIn(BaseModel):
    war_id: int
    channel_id: str
    enemy_message_id: str
    own_message_id: str
    activity_message_id: str


class FFScouterApiKeyIn(BaseModel):
    api_key: str


def _mask(value: str) -> str:
    return "•" * max(len(value) - 4, 0) + value[-4:] if len(value) > 4 else "•" * len(value)


def _api_keys_out():
    return [
        {"id": r["id"], "label": r["label"], "masked_key": _mask(r["api_key"]), "added_at": r["added_at"]}
        for r in db.list_api_keys()
    ]


def _discord_allowed_users_out():
    return db.list_discord_allowed_users()


@router.get("")
def get_settings():
    token = db.get_discord_bot_token()
    ffscouter_key = db.get_ffscouter_api_key()
    return {
        "api_key_count": len(db.get_api_keys()),
        "faction_id": db.get_faction_id(),
        "has_discord_bot_token": bool(token),
        "discord_bot_token_masked": _mask(token) if token else None,
        "discord_guild_id": db.get_setting("discord_guild_id"),
        "discord_alert_channel_id": db.get_setting("discord_alert_channel_id"),
        "has_ffscouter_api_key": bool(ffscouter_key),
        "ffscouter_api_key_masked": _mask(ffscouter_key) if ffscouter_key else None,
    }


@router.post("")
def update_settings(body: SettingsIn):
    if body.faction_id is not None:
        db.set_setting("faction_id", str(body.faction_id))
    return get_settings()


@router.get("/api-keys")
def list_api_keys():
    return _api_keys_out()


@router.post("/api-keys")
def add_api_key(body: ApiKeyIn):
    db.add_api_key(body.api_key.strip(), body.label.strip() if body.label else None)
    return _api_keys_out()


@router.delete("/api-keys/{key_id}")
def delete_api_key(key_id: int):
    db.remove_api_key(key_id)
    return _api_keys_out()


@router.post("/api-keys/validated")
def add_validated_api_key(body: ValidatedApiKeyIn):
    """Same as POST /api-keys, but for keys arriving from a less deliberate
    source (the Discord bot's /add_api_key command) - checks the key is
    actually valid and belongs to this faction before storing it, rather
    than trusting whatever text was pasted in."""
    key = body.api_key.strip()
    try:
        info = TornClient([key]).get("/key/info")["info"]
    except TornAPIError as exc:
        raise HTTPException(status_code=400, detail=f"Torn rejected this key: {exc.message}")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Couldn't reach Torn's API: {exc}")

    key_faction_id = info["user"]["faction_id"]
    our_faction_id = db.get_faction_id()
    if our_faction_id and key_faction_id != our_faction_id:
        raise HTTPException(
            status_code=400,
            detail=f"This key belongs to a member of faction {key_faction_id}, not this faction ({our_faction_id}).",
        )

    player_name = None
    try:
        player_name = TornClient([key]).user_profile(info["user"]["id"]).get("name")
    except TornAPIError:
        pass

    db.add_api_key(key, body.label.strip() if body.label else player_name)
    return {
        "player_name": player_name,
        "access_type": info["access"]["type"],
        "faction_id": key_faction_id,
    }


@router.post("/discord-bot-token")
def set_discord_bot_token(body: DiscordBotTokenIn):
    db.set_discord_bot_token(body.token.strip())
    return get_settings()


@router.post("/discord-guild-id")
def set_discord_guild_id(body: DiscordGuildIdIn):
    db.set_setting("discord_guild_id", body.guild_id.strip())
    return get_settings()


@router.post("/discord-alert-channel-id")
def set_discord_alert_channel_id(body: DiscordAlertChannelIdIn):
    db.set_setting("discord_alert_channel_id", body.channel_id.strip())
    return get_settings()


@router.get("/discord-allowed-users")
def list_discord_allowed_users():
    return _discord_allowed_users_out()


@router.post("/discord-allowed-users")
def add_discord_allowed_user(body: DiscordAllowedUserIn):
    db.add_discord_allowed_user(
        body.discord_user_id.strip(),
        body.label.strip() if body.label else None,
        body.torn_player_id,
        body.is_leadership,
    )
    return _discord_allowed_users_out()


@router.delete("/discord-allowed-users/{entry_id}")
def delete_discord_allowed_user(entry_id: int):
    db.remove_discord_allowed_user(entry_id)
    return _discord_allowed_users_out()


@router.post("/ffscouter-api-key")
def set_ffscouter_api_key(body: FFScouterApiKeyIn):
    db.set_ffscouter_api_key(body.api_key.strip())
    return get_settings()


@router.get("/discord-war-status")
def get_discord_war_status():
    war_id = db.get_setting("discord_war_status_war_id")
    return {
        "war_id": int(war_id) if war_id else None,
        "channel_id": db.get_setting("discord_war_status_channel_id"),
        "enemy_message_id": db.get_setting("discord_war_status_enemy_message_id"),
        "own_message_id": db.get_setting("discord_war_status_own_message_id"),
        "activity_message_id": db.get_setting("discord_war_status_activity_message_id"),
    }


@router.post("/discord-war-status")
def set_discord_war_status(body: DiscordWarStatusIn):
    db.set_setting("discord_war_status_war_id", str(body.war_id))
    db.set_setting("discord_war_status_channel_id", body.channel_id)
    db.set_setting("discord_war_status_enemy_message_id", body.enemy_message_id)
    db.set_setting("discord_war_status_own_message_id", body.own_message_id)
    db.set_setting("discord_war_status_activity_message_id", body.activity_message_id)
    return get_discord_war_status()


@router.delete("/discord-war-status")
def clear_discord_war_status():
    db.set_setting("discord_war_status_war_id", "")
    db.set_setting("discord_war_status_channel_id", "")
    db.set_setting("discord_war_status_enemy_message_id", "")
    db.set_setting("discord_war_status_own_message_id", "")
    db.set_setting("discord_war_status_activity_message_id", "")
    return get_discord_war_status()


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
