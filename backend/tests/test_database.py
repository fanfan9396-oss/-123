import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.db import SCHEMA_VERSION, DatabaseError, connect_database, initialize_database


class DatabaseFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "project.sqlite3"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initializes_schema_and_can_reopen(self):
        initialize_database(self.db_path)
        with closing(connect_database(self.db_path)) as conn:
            version = conn.execute(
                "SELECT version FROM schema_version WHERE id = 1"
            ).fetchone()[0]
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertTrue({"projects", "sources", "excerpts"}.issubset(tables))

        initialize_database(self.db_path)
        with closing(connect_database(self.db_path)) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 0
            )

    def test_foreign_keys_and_source_snapshot_contract(self):
        initialize_database(self.db_path)
        snapshot = "第一行\n第二行\n"
        digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        with closing(connect_database(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO projects (id, name, goal, description) VALUES (?, ?, ?, ?)",
                ("project-1", "Demo", "蒸馏", "测试项目"),
            )
            conn.execute(
                """
                INSERT INTO sources (
                    id, project_id, source_type, title, format, snapshot_text,
                    snapshot_sha256, original_file_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "source-1",
                    "project-1",
                    "other",
                    "示例资料",
                    "md",
                    snapshot,
                    digest,
                    "original-hash",
                ),
            )
            conn.execute(
                """
                INSERT INTO excerpts (
                    id, source_id, start_line, end_line, excerpt_text
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("excerpt-1", "source-1", 1, 2, snapshot),
            )
            self.assertEqual(
                conn.execute("PRAGMA foreign_keys").fetchone()[0], 1
            )
            self.assertEqual(
                conn.execute(
                    "SELECT snapshot_sha256 FROM sources WHERE id = ?",
                    ("source-1",),
                ).fetchone()[0],
                digest,
            )

    def test_invalid_source_format_and_excerpt_range_are_rejected(self):
        initialize_database(self.db_path)
        with closing(connect_database(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO projects (id, name) VALUES (?, ?)",
                ("project-1", "Demo"),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO sources (
                        id, project_id, source_type, title, format, snapshot_text,
                        snapshot_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "source-bad",
                        "project-1",
                        "other",
                        "Bad",
                        "pdf",
                        "text",
                        "hash",
                    ),
                )
            conn.execute(
                """
                INSERT INTO sources (
                    id, project_id, source_type, title, format, snapshot_text,
                    snapshot_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("source-1", "project-1", "other", "Good", "txt", "text", "a" * 64),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO excerpts (
                        id, source_id, start_line, end_line, excerpt_text
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    ("excerpt-bad", "source-1", 0, 1, "text"),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO excerpts (
                        id, source_id, start_line, end_line, excerpt_text
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    ("excerpt-bad-2", "source-1", 2, 1, "text"),
                )

    def test_migrates_v1_project_database_without_losing_project(self):
        connection = sqlite3.connect(self.db_path)
        connection.executescript(
            """
            CREATE TABLE schema_version (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, applied_at TEXT NOT NULL DEFAULT '');
            INSERT INTO schema_version (id, version) VALUES (1, 1);
            CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT, description TEXT, schema_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '');
            CREATE TABLE sources (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), source_type TEXT NOT NULL, title TEXT NOT NULL, author_or_creator TEXT, published_at TEXT, source_uri TEXT, original_path TEXT, notes TEXT, format TEXT NOT NULL, snapshot_text TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL, original_file_sha256 TEXT, imported_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '', UNIQUE(project_id, snapshot_sha256));
            CREATE TABLE excerpts (id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id), start_line INTEGER NOT NULL, end_line INTEGER NOT NULL, excerpt_text TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT '');
            INSERT INTO projects (id, name) VALUES ('legacy-project', 'Legacy');
            """
        )
        connection.commit()
        connection.close()
        initialize_database(self.db_path)
        with closing(connect_database(self.db_path)) as conn:
            version = conn.execute("SELECT version FROM schema_version WHERE id=1").fetchone()[0]
            project = conn.execute("SELECT name FROM projects WHERE id='legacy-project'").fetchone()[0]
            columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual(project, "Legacy")
        self.assertIn("pending_text", columns)
        self.assertIn("pending_file_sha256", columns)

    def test_migrates_schema_v5_to_v6_and_creates_plan_mechanism_link(self):
        initialize_database(self.db_path)
        with closing(connect_database(self.db_path)) as conn:
            conn.execute("DROP TABLE skill_plan_mechanisms")
            conn.execute("ALTER TABLE mechanisms DROP COLUMN review_note")
            conn.execute("UPDATE schema_version SET version=5 WHERE id=1")
            conn.commit()
        initialize_database(self.db_path)
        with closing(connect_database(self.db_path)) as conn:
            version = conn.execute("SELECT version FROM schema_version WHERE id=1").fetchone()[0]
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            mechanism_columns = {row[1] for row in conn.execute("PRAGMA table_info(mechanisms)")}
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertIn("skill_plan_mechanisms", tables)
        self.assertIn("review_note", mechanism_columns)
    def test_migrates_schema_v7_to_v8_and_creates_evaluation_tables(self):
        initialize_database(self.db_path)
        with closing(connect_database(self.db_path)) as conn:
            for table in ("quality_reports", "evaluations", "scenarios"):
                conn.execute(f"DROP TABLE {table}")
            conn.execute("UPDATE schema_version SET version=7 WHERE id=1")
            conn.commit()
        initialize_database(self.db_path)
        with closing(connect_database(self.db_path)) as conn:
            version = conn.execute("SELECT version FROM schema_version WHERE id=1").fetchone()[0]
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            scenario_columns = {row[1] for row in conn.execute("PRAGMA table_info(scenarios)")}
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertTrue({"scenarios", "evaluations", "quality_reports"}.issubset(tables))
        self.assertIn("version_fingerprint", scenario_columns)

    def test_migrates_s2a_schema_v2_to_v3(self):
        initialize_database(self.db_path)
        with closing(connect_database(self.db_path)) as conn:
            conn.execute("UPDATE schema_version SET version=2 WHERE id=1")
        initialize_database(self.db_path)
        with closing(connect_database(self.db_path)) as conn:
            version = conn.execute("SELECT version FROM schema_version WHERE id=1").fetchone()[0]
            columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertIn("pending_file_sha256", columns)
    def test_unregistered_existing_database_is_not_overwritten(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("CREATE TABLE user_table (value TEXT)")
        with self.assertRaises(DatabaseError):
            initialize_database(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertIsNotNone(
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'user_table'"
                ).fetchone()
            )

    def test_transaction_rolls_back_on_constraint_failure(self):
        initialize_database(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            with closing(connect_database(self.db_path)) as conn:
                conn.execute(
                    "INSERT INTO projects (id, name) VALUES (?, ?)",
                    ("project-1", "Demo"),
                )
                conn.execute(
                    "INSERT INTO projects (id, name) VALUES (?, ?)",
                    ("project-1", "Duplicate"),
                )
        with closing(connect_database(self.db_path)) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 0
            )


if __name__ == "__main__":
    unittest.main()
