"""Offline operator tools. Never print connection strings or raw exceptions."""
import argparse
import json
import os
from pathlib import Path
from .database import Database
from .transfer import export_bundle, restore_bundle


def _attach_video_directory(db, isolated):
    configured = os.getenv(
        "SMH_TEST_EDUCATION_VIDEO_STORAGE_DIR" if isolated
        else "SMH_EDUCATION_VIDEO_STORAGE_DIR"
    )
    default = db.directory / "education-videos"
    db.education_video_data_dir = Path(configured).resolve() if configured else default.resolve()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["migrate", "export", "restore", "import-sqlite", "health"])
    p.add_argument("--file")
    p.add_argument("--sqlite-dir", help="Isolated test DB or legacy SQLite import source")
    p.add_argument("--external-or-development", action="store_true",
                   help="Confirm migration target is external PostgreSQL or development, not Replit-managed production")
    args = p.parse_args()
    isolated = os.getenv("SMH_ISOLATED_TEST_INSTANCE", "false").lower() == "true"
    url = (os.getenv("SMH_TEST_DATABASE_URL") if isolated else
           os.getenv("SMH_DATABASE_URL") or os.getenv("DATABASE_URL"))
    if isolated and not url:
        raise ValueError("SMH_TEST_DATABASE_URL is required for isolated test operations.")
    if args.command == "migrate":
        if not args.external_or_development:
            raise ValueError("Use Replit Publish for managed production schema. Explicit target confirmation required.")
        import psycopg
        with psycopg.connect(url) as conn:
            for migration in sorted(Path("migrations").glob("[0-9][0-9][0-9]_*.sql")):
                conn.execute(migration.read_text())
        print("Migrations applied.")
        return
    if args.command == "import-sqlite":
        # Export source only; do not destroy it. Target must be empty.
        source = Database(args.sqlite_dir)
        for row in source.rows("SELECT owner,data FROM drafts"):
            d = json.loads(row["data"])
            source.save_draft(row["owner"], d)
        for row in source.rows("SELECT id,payload FROM operations"):
            data = json.loads(row["payload"])
            source.persist_images(data)
            source.execute("UPDATE operations SET payload=? WHERE id=?", (json.dumps(data), row["id"]))
        journal = source.directory / "receipts.jsonl"
        if journal.exists():
            for line in journal.read_text().splitlines():
                r = json.loads(line)
                source.execute("INSERT INTO receipts VALUES (?,?) ON CONFLICT(id) DO NOTHING", (r["id"], json.dumps(r["result"])))
        export_bundle(source, args.file)
        source.conn.close()
        target = Database(os.getenv("SMH_TEST_DATA_DIR", "data-test") if isolated else
                          os.getenv("SMH_DATA_DIR", "data"), url)
        _attach_video_directory(target, isolated)
        print(json.dumps(restore_bundle(target, args.file)))
        target.conn.close()
        return
    if args.sqlite_dir and os.getenv("SMH_TEST_MODE") != "1":
        raise ValueError("SQLite tools require SMH_TEST_MODE=1.")
    data_dir = os.getenv("SMH_TEST_DATA_DIR", "data-test") if isolated else os.getenv("SMH_DATA_DIR", "data")
    db = Database(args.sqlite_dir or data_dir, None if args.sqlite_dir else url)
    _attach_video_directory(db, isolated)
    try:
        if args.command == "export":
            export_bundle(db, args.file)
            print("Export complete; contains private data. Store encrypted off-host.")
        elif args.command == "restore":
            print(json.dumps(restore_bundle(db, args.file)))
        else:
            print(json.dumps({"database": db.integrity(), "postgres": db.postgres}))
    finally:
        db.conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Operation failed ({type(exc).__name__}); no credentials logged.")
        raise SystemExit(1) from None
