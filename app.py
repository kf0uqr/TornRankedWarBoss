from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend import db
from backend.routes import armory, settings, wars

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

db.init_db()

app = FastAPI(title="Torn Ranked War Manager")
app.include_router(settings.router)
app.include_router(wars.router)
app.include_router(armory.router)
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8787, reload=True)
