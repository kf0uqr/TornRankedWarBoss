from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend import armory, db
from backend.deps import require_client, require_leadership, torn_error_to_http
from backend.torn_api import TornAPIError

router = APIRouter(prefix="/api/armory", tags=["armory"], dependencies=[Depends(require_leadership)])


class TargetUpdateIn(BaseModel):
    target_qty: int


class TargetCreateIn(BaseModel):
    item_id: int
    item_name: str
    armory_category: str
    torn_item_category: str
    target_qty: int


@router.get("/targets")
def list_targets():
    conn = db.get_connection()
    try:
        return armory.get_armory_targets(conn)
    finally:
        conn.close()


@router.post("/targets")
def create_target(body: TargetCreateIn):
    conn = db.get_connection()
    try:
        armory.add_armory_target(
            conn, body.item_id, body.item_name, body.armory_category, body.torn_item_category, body.target_qty
        )
        return armory.get_armory_targets(conn)
    finally:
        conn.close()


@router.patch("/targets/{item_id}")
def update_target(item_id: int, body: TargetUpdateIn):
    conn = db.get_connection()
    try:
        armory.set_armory_target(conn, item_id, body.target_qty)
        return armory.get_armory_targets(conn)
    finally:
        conn.close()


@router.delete("/targets/{item_id}")
def delete_target(item_id: int):
    conn = db.get_connection()
    try:
        armory.remove_armory_target(conn, item_id)
        return armory.get_armory_targets(conn)
    finally:
        conn.close()


@router.get("/restock")
def get_restock():
    conn = db.get_connection()
    try:
        targets = armory.get_armory_targets(conn)
    finally:
        conn.close()

    client = require_client()
    try:
        return armory.compute_restock(client, targets)
    except TornAPIError as exc:
        raise torn_error_to_http(exc)
    finally:
        client.close()
