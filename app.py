"""A small, single-process Mind Board server with transactional SQLite storage."""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("MINDBOARD_DB", str(ROOT / "data" / "mindboard.sqlite3")))
MAX_BODY = 8 * 1024 * 1024
INDEX_KEY = "mindboard-index-v1"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DATABASE, timeout=10)
    try:
        connection.execute("PRAGMA busy_timeout = 10000")
        with connection:
            yield connection
    finally:
        connection.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("CREATE TABLE IF NOT EXISTS storage (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK (id = 1), revision INTEGER NOT NULL)")
        db.execute("INSERT OR IGNORE INTO metadata VALUES (1, 0)")
    yield


app = FastAPI(title="Mind Board", lifespan=lifespan)


@app.middleware("http")
async def protect_writes(request: Request, call_next):
    if request.method == "PUT":
        # JSON + a custom header prevents cross-site form submissions. No CORS is enabled.
        origin = request.headers.get("origin")
        if (request.headers.get("x-mindboard") != "1"
                or request.headers.get("content-type", "").split(";")[0] != "application/json"
                or (origin and urlsplit(origin).netloc != request.headers.get("host"))):
            return JSONResponse({"detail": "Same-origin JSON requests only"}, status_code=403)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                return JSONResponse({"detail": "Board collection exceeds 8 MiB"}, status_code=413)
        request._body = bytes(body)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


class StateUpdate(BaseModel):
    revision: int = Field(ge=0)
    storage: dict[str, str]


def validate_storage(storage: dict[str, str]) -> None:
    """Keep the editor's versioned format, including layout and imported analyses."""
    try:
        index = json.loads(storage[INDEX_KEY])
        boards = index["list"]
        if not isinstance(boards, list) or not boards:
            raise ValueError("Missing boards")
        ids = [item["id"] for item in boards]
        if not all(isinstance(id_, str) and 0 < len(id_) <= 128 for id_ in ids):
            raise ValueError("Invalid board IDs")
        if len(set(ids)) != len(ids) or index["cur"] not in ids:
            raise ValueError("Invalid index")
        if set(storage) != {INDEX_KEY, *("mindboard-board-" + id_ for id_ in ids)}:
            raise ValueError("Missing or orphaned boards")
        for item in boards:
            if not isinstance(item.get("name", ""), str):
                raise ValueError("Invalid board name")
            board = json.loads(storage["mindboard-board-" + item["id"]])
            if not isinstance(board, dict) or not isinstance(board["notes"], list):
                raise ValueError("Invalid board")
            if not all(isinstance(note, dict) for note in board["notes"]):
                raise ValueError("Invalid notes")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, "Invalid board collection") from exc


@app.get("/api/state")
def read_state():
    with connect() as db:
        # One read transaction keeps the revision and snapshot consistent.
        db.execute("BEGIN")
        revision = db.execute("SELECT revision FROM metadata WHERE id = 1").fetchone()[0]
        storage = dict(db.execute("SELECT key, value FROM storage"))
    return {"revision": revision, "storage": storage}


@app.put("/api/state")
def write_state(update: StateUpdate):
    validate_storage(update.storage)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        revision = db.execute("SELECT revision FROM metadata WHERE id = 1").fetchone()[0]
        if revision != update.revision:
            raise HTTPException(409, "Another tab or device saved changes. Reload before editing.")
        db.execute("DELETE FROM storage")
        db.executemany("INSERT INTO storage VALUES (?, ?)", update.storage.items())
        db.execute("UPDATE metadata SET revision = revision + 1 WHERE id = 1")
    return {"revision": revision + 1}


@app.get("/health")
def health():
    with connect() as db:
        db.execute("SELECT revision FROM metadata WHERE id = 1").fetchone()
    return {"status": "ok"}


@app.get("/storage.js", include_in_schema=False)
def storage_script():
    return FileResponse(ROOT / "storage.js", media_type="text/javascript")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "Mind Board – Architecture Studio.html")