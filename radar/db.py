import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings


def utcnow():
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS papers (
                    id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL,
                    version TEXT NOT NULL, title TEXT NOT NULL, authors TEXT NOT NULL,
                    abstract TEXT NOT NULL, published TEXT NOT NULL, updated TEXT NOT NULL,
                    categories TEXT NOT NULL, url TEXT NOT NULL, pdf_url TEXT NOT NULL,
                    discovered_at TEXT NOT NULL, is_revision INTEGER NOT NULL DEFAULT 0,
                    favorite INTEGER NOT NULL DEFAULT 0, is_read INTEGER NOT NULL DEFAULT 0,
                    brief TEXT, analysis TEXT, UNIQUE(source, external_id, version)
                );
                CREATE INDEX IF NOT EXISTS papers_date ON papers(updated DESC);
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                    status TEXT NOT NULL, reason TEXT NOT NULL, found INTEGER DEFAULT 0,
                    selected INTEGER DEFAULT 0, error TEXT, details_planned INTEGER DEFAULT 0,
                    detailed_limit INTEGER NOT NULL DEFAULT 3
                );
                CREATE TABLE IF NOT EXISTS bulletin (
                    run_id INTEGER REFERENCES runs(id), paper_id INTEGER REFERENCES papers(id),
                    PRIMARY KEY(run_id, paper_id)
                );
                CREATE TABLE IF NOT EXISTS bulletin_exclusions (
                    day TEXT NOT NULL, paper_id INTEGER NOT NULL REFERENCES papers(id),
                    removed_at TEXT NOT NULL, PRIMARY KEY(day, paper_id)
                );
                CREATE TABLE IF NOT EXISTS deleted_bulletins (
                    day TEXT PRIMARY KEY, deleted_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, paper_id INTEGER NOT NULL REFERENCES papers(id),
                    kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT,
                    progress TEXT, UNIQUE(paper_id, kind)
                );
                CREATE TABLE IF NOT EXISTS source_requests (
                    id INTEGER PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL,
                    purpose TEXT NOT NULL, status INTEGER, retry_after TEXT
                );
            """)
            # Migraciones aditivas: no reemplazan filas, resultados ni trabajos cancelados.
            for table, columns in {
                "papers": {"interest": "INTEGER NOT NULL DEFAULT 0", "document_type": "TEXT NOT NULL DEFAULT ''",
                           "has_pdf": "INTEGER NOT NULL DEFAULT 1", "overview": "TEXT"},
                "runs": {"source_stats": "TEXT NOT NULL DEFAULT '{}'", "detail_quotas": "TEXT NOT NULL DEFAULT '{}'",
                         "bulletin_day": "TEXT NOT NULL DEFAULT ''"},
            }.items():
                existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                for column, definition in columns.items():
                    if column not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def rows(self, query, params=()):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def execute(self, query, params=()):
        with self.connect() as conn:
            cursor = conn.execute(query, params)
            return cursor.lastrowid

    def get_meta(self, key, default=None):
        rows = self.rows("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_meta(self, key, value):
        self.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, json.dumps(value, ensure_ascii=False)))

    def settings(self):
        return Settings.model_validate(self.get_meta("settings", {}))

    def add_papers(self, papers, *, connection=None):
        if connection is None:
            with self.connect() as conn:
                return self.add_papers(papers, connection=conn)
        inserted = []
        for paper in papers:
            previous = connection.execute("SELECT 1 FROM papers WHERE source=? AND external_id=?",
                                          (paper.source, paper.external_id)).fetchone()
            cursor = connection.execute("""INSERT OR IGNORE INTO papers
                (source,external_id,version,title,authors,abstract,published,updated,categories,
                  url,pdf_url,discovered_at,is_revision,document_type,has_pdf) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (paper.source, paper.external_id, paper.version, paper.title,
                 json.dumps(paper.authors, ensure_ascii=False), paper.abstract,
                 paper.published, paper.updated, json.dumps(paper.categories),
                 paper.url, paper.pdf_url, utcnow(), int(bool(previous)), paper.document_type, int(paper.has_pdf)))
            if cursor.rowcount:
                inserted.append(cursor.lastrowid)
        return inserted

    def paper(self, paper_id):
        rows = self.rows("SELECT * FROM papers WHERE id=?", (paper_id,))
        return decode_paper(rows[0]) if rows else None

    def queue(self, paper_id, kind, retry=False, regenerate=False):
        now = utcnow()
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO jobs(paper_id,kind,created_at,updated_at) VALUES(?,?,?,?)",
                         (paper_id, kind, now, now))
            if retry or regenerate:
                conn.execute("""UPDATE jobs SET status='queued',error=NULL,progress=NULL,updated_at=?
                    WHERE paper_id=? AND kind=? AND (status IN ('error','cancelled') OR (?=1 AND status='done'))""",
                             (now, paper_id, kind, int(regenerate)))

    def recover(self):
        self.execute("UPDATE jobs SET status='queued',progress='Recuperado tras reinicio' WHERE status='running'")
        self.execute("UPDATE runs SET status='interrupted',finished_at=? WHERE status='running'", (utcnow(),))


def decode_paper(row):
    row = dict(row)
    for field in ("authors", "categories", "brief", "analysis", "overview"):
        row[field] = json.loads(row[field]) if row[field] is not None else None
    return row
