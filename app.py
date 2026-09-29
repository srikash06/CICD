"""Single-instance order API with transactional idempotency and persistent storage."""
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

log = logging.getLogger("orders")
logging.basicConfig(level=logging.INFO)


@contextmanager
def database():
    conn = sqlite3.connect(os.getenv("DATABASE_PATH", "data/orders.db"), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app):
    if len(os.getenv("API_KEY", "")) < 32:
        raise RuntimeError("API_KEY must contain at least 32 characters")
    Path(os.getenv("DATABASE_PATH", "data/orders.db")).parent.mkdir(parents=True, exist_ok=True)
    with database() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(Path("migrations/001_orders.sql").read_text())
    yield


app = FastAPI(title="Order Service", lifespan=lifespan)


def authenticate(x_api_key: str = Header(default="")):
    if not hmac.compare_digest(x_api_key, os.environ["API_KEY"]):
        raise HTTPException(401, "Invalid API key")


class OrderInput(BaseModel):
    product: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
    quantity: int = Field(gt=0, le=1000, strict=True)
    unit_price_paise: int = Field(gt=0, le=10000000, strict=True)


@app.middleware("http")
async def request_log(request: Request, call_next):
    request_id = str(uuid.uuid4())
    start = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    log.info(json.dumps({"request_id": request_id, "method": request.method,
                         "path": request.url.path, "status": response.status_code,
                         "duration_ms": round((time.monotonic() - start) * 1000, 2)}))
    return response


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    try:
        with database() as conn:
            conn.execute("SELECT id FROM orders LIMIT 1")
    except sqlite3.Error:
        raise HTTPException(503, "Database unavailable") from None
    return {"status": "ready"}


@app.get("/version")
def version():
    return {"version": os.getenv("APP_VERSION", "local")}


@app.post("/orders", status_code=201, dependencies=[Depends(authenticate)])
def create_order(order: OrderInput, response: Response,
                 idempotency_key: str = Header(min_length=8, max_length=100)):
    payload = order.model_dump()
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with database() as conn:
        # Serialize writers, so simultaneous retries cannot create duplicate orders.
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT * FROM orders WHERE idempotency_key=?",
                                (idempotency_key,)).fetchone()
        if existing:
            if existing["fingerprint"] != fingerprint:
                raise HTTPException(409, "Idempotency key reused with different payload")
            response.status_code = 200
            return public_order(existing)
        order_id = str(uuid.uuid4())
        conn.execute("""INSERT INTO orders
            (id, product, quantity, unit_price_paise, status, idempotency_key, fingerprint)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
                     (order_id, order.product, order.quantity, order.unit_price_paise,
                      idempotency_key, fingerprint))
        return public_order(conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())


def public_order(row):
    result = {key: row[key] for key in
              ("id", "product", "quantity", "unit_price_paise", "status", "created_at")}
    result["total_paise"] = row["quantity"] * row["unit_price_paise"]
    return result


@app.get("/orders", dependencies=[Depends(authenticate)])
def list_orders(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    with database() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at, id LIMIT ? OFFSET ?",
                            (limit, offset)).fetchall()
        return {"items": [public_order(row) for row in rows], "limit": limit, "offset": offset}


@app.get("/orders/{order_id}", dependencies=[Depends(authenticate)])
def get_order(order_id: str):
    with database() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Order not found")
        return public_order(row)


@app.post("/orders/{order_id}/cancel", dependencies=[Depends(authenticate)])
def cancel_order(order_id: str):
    with database() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Order not found")
        conn.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
        return public_order(conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
