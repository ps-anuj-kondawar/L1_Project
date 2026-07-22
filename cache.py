import sqlite3
import hashlib
import json
import time

DB_PATH     = "./cache.db"
CACHE_TTL   = 60 * 60 * 24 * 30   # 30 days in seconds

def _init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS osha_cache "
            "(chemical TEXT PRIMARY KEY, limits_json TEXT, created_at REAL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS summary_cache "
            "(violations_hash TEXT PRIMARY KEY, summary TEXT, created_at REAL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS input_cache "
            "(input_hash TEXT PRIMARY KEY, report_json TEXT, created_at REAL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS conversation_cache "
            "(query_hash TEXT PRIMARY KEY, response TEXT, created_at REAL)"
        )
        conn.commit()

_init_db()

def _get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)

def get_osha_limits(chemical: str) -> dict | None:
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT limits_json, created_at FROM osha_cache WHERE chemical = ?",
                (chemical.lower().strip(),)
            ).fetchone()
        if row and (time.time() - row[1]) < CACHE_TTL:
            return json.loads(row[0])
    except Exception:
        pass
    return None

def set_osha_limits(chemical: str, limits: dict) -> None:
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO osha_cache VALUES (?, ?, ?)",
                (chemical.lower().strip(), json.dumps(limits), time.time())
            )
    except Exception:
        pass

# ── LAYER 2: Exact Input Cache (using SQLite for precision safety) ─────────

def get_semantic_cache(input_text: str) -> dict | None:
    try:
        h = hashlib.sha256(input_text.strip().encode()).hexdigest()
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT report_json, created_at FROM input_cache WHERE input_hash = ?", (h,)
            ).fetchone()
        if row and (time.time() - row[1]) < CACHE_TTL:
            return json.loads(row[0])
    except Exception:
        pass
    return None

def set_semantic_cache(input_text: str, report_json: str) -> None:
    try:
        h = hashlib.sha256(input_text.strip().encode()).hexdigest()
        with _get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO input_cache VALUES (?, ?, ?)",
                (h, report_json, time.time())
            )
    except Exception:
        pass

# ── LAYER 3: LLM Summary SQLite cache ───────────────────────────────────────

def _hash_violations(violations: list[str]) -> str:
    key = "|".join(sorted(violations))
    return hashlib.sha256(key.encode()).hexdigest()

def get_summary_cache(violations: list[str]) -> str | None:
    try:
        h = _hash_violations(violations)
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT summary FROM summary_cache WHERE violations_hash = ?", (h,)
            ).fetchone()
        return row[0] if row else None
    except Exception:
        pass
    return None

def set_summary_cache(violations: list[str], summary: str) -> None:
    try:
        h = _hash_violations(violations)
        with _get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO summary_cache VALUES (?, ?, ?)",
                (h, summary, time.time())
            )
    except Exception:
        pass


def get_conversation_cache(message: str, history: list) -> str | None:
    try:
        history_str = json.dumps(history)
        key = f"{history_str}|||{message.strip()}"
        h = hashlib.sha256(key.encode()).hexdigest()
        
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT response, created_at FROM conversation_cache WHERE query_hash = ?", (h,)
            ).fetchone()
        if row and (time.time() - row[1]) < CACHE_TTL:
            return row[0]
    except Exception:
        pass
    return None


def set_conversation_cache(message: str, history: list, response: str) -> None:
    try:
        history_str = json.dumps(history)
        key = f"{history_str}|||{message.strip()}"
        h = hashlib.sha256(key.encode()).hexdigest()
        
        with _get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO conversation_cache VALUES (?, ?, ?)",
                (h, response, time.time())
            )
    except Exception:
        pass
