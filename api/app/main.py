from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError

from app.api.auth import router as auth_router
from app.api.read import router as read_router
from app.config import settings
from app.db import engine

app = FastAPI(
    title="Casino Admin API",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.include_router(auth_router)
app.include_router(read_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/db-check")
def db_check():
    """Phase 0 spike: proves the API can reach PostgreSQL and that the seed was restored."""
    try:
        with engine.connect() as conn:
            version = conn.execute(text("select version()")).scalar_one()
            try:
                note = conn.execute(
                    text("select note from spike_check order by id limit 1")
                ).scalar_one_or_none()
            except ProgrammingError:  # table missing -> seed not loaded
                conn.rollback()
                note = None
    except SQLAlchemyError as exc:
        return JSONResponse(
            status_code=503,
            content={"database": "error", "detail": str(exc.__cause__ or exc)},
        )
    return {
        "database": "ok",
        "version": version,
        "seed_loaded": note is not None,
        "seed_note": note,
    }


# Must be mounted last so it does not shadow the /api routes.
_web_dir = Path(settings.web_dir)
if _web_dir.is_dir():
    app.mount("/", StaticFiles(directory=_web_dir, html=True), name="web")
