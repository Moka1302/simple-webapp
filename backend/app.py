import os
import time
from functools import wraps

from flask import Flask, jsonify, request
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import psycopg2

app = Flask(__name__)

# ---- Database connection settings (from environment variables) ----
DB_HOST = os.environ.get("DB_HOST", "db")
DB_NAME = os.environ.get("DB_NAME", "webappdb")
DB_USER = os.environ.get("DB_USER", "appuser")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "apppass")

# ============================================================
# Prometheus metrics
# ============================================================

# --- Request count (labeled by endpoint, method, and status code) ---
REQUEST_COUNT = Counter(
    "app_requests_total",
    "Total number of HTTP requests",
    ["endpoint", "method", "http_status"],
)

# --- API performance: how long each endpoint takes to respond ---
REQUEST_LATENCY = Histogram(
    "app_request_latency_seconds",
    "Request latency in seconds",
    ["endpoint"],
)

# --- Errors: any failure, labeled by where it happened and what kind ---
ERROR_COUNT = Counter(
    "app_errors_total",
    "Total number of application errors",
    ["endpoint", "error_type"],
)

# --- DB performance: how long each DB operation takes ---
DB_QUERY_LATENCY = Histogram(
    "db_query_latency_seconds",
    "Database query latency in seconds",
    ["operation"],
)

# --- DB errors: failed queries/connections, labeled by operation ---
DB_ERROR_COUNT = Counter(
    "db_errors_total",
    "Total number of database errors",
    ["operation"],
)


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )


def timed_db_call(operation):
    """Wrap a DB-calling function to record duration + errors as Prometheus metrics."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                return func(*args, **kwargs)
            except Exception:
                DB_ERROR_COUNT.labels(operation=operation).inc()
                raise
            finally:
                DB_QUERY_LATENCY.labels(operation=operation).observe(time.time() - start)
        return wrapper
    return decorator


# ============================================================
# DB access functions (each individually timed for DB performance metrics)
# ============================================================

@timed_db_call("select_version")
def db_select_version():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    cur.close()
    conn.close()
    return version


@timed_db_call("select_items")
def db_select_items():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, description, created_at FROM items ORDER BY id;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@timed_db_call("insert_item")
def db_insert_item(name, description):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO items (name, description) VALUES (%s, %s) RETURNING id, created_at;",
        (name, description),
    )
    new_id, created_at = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return new_id, created_at


# ============================================================
# Routes
# ============================================================

@app.route("/api/hello")
def hello():
    endpoint = "/api/hello"
    start = time.time()
    status = 200
    body = {"message": "Hello from the backend!", "status": "ok"}
    REQUEST_LATENCY.labels(endpoint=endpoint).observe(time.time() - start)
    REQUEST_COUNT.labels(endpoint=endpoint, method=request.method, http_status=status).inc()
    return jsonify(body), status


@app.route("/api/db-check")
def db_check():
    endpoint = "/api/db-check"
    start = time.time()
    try:
        version = db_select_version()
        body = {"status": "connected", "postgres_version": version}
        status = 200
    except Exception as e:
        ERROR_COUNT.labels(endpoint=endpoint, error_type=type(e).__name__).inc()
        body = {"status": "error", "detail": str(e)}
        status = 500
    REQUEST_LATENCY.labels(endpoint=endpoint).observe(time.time() - start)
    REQUEST_COUNT.labels(endpoint=endpoint, method=request.method, http_status=status).inc()
    return jsonify(body), status


@app.route("/api/items", methods=["GET", "POST"])
def items():
    endpoint = "/api/items"
    start = time.time()

    if request.method == "POST":
        try:
            payload = request.get_json(force=True) or {}
            name = payload.get("name", "").strip()
            description = payload.get("description", "").strip()
            if not name:
                status = 400
                body = {"status": "error", "detail": "name is required"}
            else:
                new_id, created_at = db_insert_item(name, description)
                status = 201
                body = {
                    "status": "created",
                    "item": {
                        "id": new_id,
                        "name": name,
                        "description": description,
                        "created_at": created_at.isoformat(),
                    },
                }
        except Exception as e:
            ERROR_COUNT.labels(endpoint=endpoint, error_type=type(e).__name__).inc()
            status = 500
            body = {"status": "error", "detail": str(e)}

        REQUEST_LATENCY.labels(endpoint=endpoint).observe(time.time() - start)
        REQUEST_COUNT.labels(endpoint=endpoint, method=request.method, http_status=status).inc()
        return jsonify(body), status

    # GET — read
    try:
        rows = db_select_items()
        body = [
            {
                "id": r[0],
                "name": r[1],
                "description": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ]
        status = 200
    except Exception as e:
        ERROR_COUNT.labels(endpoint=endpoint, error_type=type(e).__name__).inc()
        body = {"status": "error", "detail": str(e)}
        status = 500

    REQUEST_LATENCY.labels(endpoint=endpoint).observe(time.time() - start)
    REQUEST_COUNT.labels(endpoint=endpoint, method=request.method, http_status=status).inc()
    return jsonify(body), status


@app.route("/api/health")
def health():
    endpoint = "/api/health"
    REQUEST_COUNT.labels(endpoint=endpoint, method=request.method, http_status=200).inc()
    return jsonify({"status": "healthy"})


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
