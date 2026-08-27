from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import db
from backend.routes import activity, armory, dashboard, giveaways, settings, stat_snapshots, stats, travel, wars
from backend.torn_api import TornRateLimitError

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

db.init_db()

app = FastAPI(title="Torn Ranked War Manager")
app.include_router(settings.router)
app.include_router(wars.router)
app.include_router(armory.router)
app.include_router(stats.router)
app.include_router(travel.router)
app.include_router(activity.router)
app.include_router(giveaways.router)
app.include_router(dashboard.router)
app.include_router(stat_snapshots.router)


@app.exception_handler(TornRateLimitError)
async def rate_limit_handler(request: Request, exc: TornRateLimitError):
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Reached this app's Torn API request budget - waiting for it to free up.",
            "retry_after": exc.retry_after,
        },
        headers={"Retry-After": str(int(exc.retry_after) + 1)},
    )


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8787, reload=True)
