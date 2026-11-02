"""Keeps the app's files (results, drafts, history, your lists, settings) in a database, so nothing
is lost when a free server restarts. The app keeps working with ordinary files; this copies every
change into the database and puts everything back on start-up. Does nothing without DATABASE_URL."""
import hashlib
import os
import threading

import settings

_lock = threading.Lock()
_known = {}  # path -> hash of what the database holds


def enabled():
    return bool(os.environ.get("DATABASE_URL"))


def _connect():
    import psycopg
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=15)


def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS app_files (
        path TEXT PRIMARY KEY, content BYTEA NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")


def _local_files():
    root = settings.DATA_ROOT
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for name in files:
            full = os.path.join(folder, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if rel.endswith((".csv", ".json")) or rel == ".env":
                yield rel, full


def restore():
    """Writes every stored file back to the data folder. Run once at start-up."""
    if not enabled():
        return 0
    with _lock, _connect() as conn:
        _ensure(conn)
        rows = conn.execute("SELECT path, content FROM app_files").fetchall()
        for rel, content in rows:
            full = os.path.join(settings.DATA_ROOT, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(bytes(content))
            _known[rel] = hashlib.sha1(bytes(content)).hexdigest()
    return len(rows)


def sync():
    """Saves new and changed files, and forgets deleted ones."""
    if not enabled():
        return
    with _lock:
        current = {}
        for rel, full in _local_files():
            with open(full, "rb") as f:
                current[rel] = f.read()
        changed = {rel: data for rel, data in current.items()
                   if _known.get(rel) != hashlib.sha1(data).hexdigest()}
        removed = [rel for rel in _known if rel not in current]
        if not changed and not removed:
            return
        with _connect() as conn:
            _ensure(conn)
            with conn.cursor() as cur:
                for rel, data in changed.items():
                    cur.execute("""INSERT INTO app_files (path, content, updated_at) VALUES (%s, %s, now())
                                   ON CONFLICT (path) DO UPDATE SET content = EXCLUDED.content, updated_at = now()""",
                                (rel, data))
                if removed:
                    cur.execute("DELETE FROM app_files WHERE path = ANY(%s)", (removed,))
        for rel, data in changed.items():
            _known[rel] = hashlib.sha1(data).hexdigest()
        for rel in removed:
            _known.pop(rel, None)
