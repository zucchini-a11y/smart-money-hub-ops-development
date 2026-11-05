"""Provider-independent consistent export and transactional, empty-target restore."""
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

LEGACY_TABLES = ("kv", "trades", "operations", "events", "drafts", "buttons",
                 "applications", "access", "errors", "receipts")
V2_TABLES = (*LEGACY_TABLES, "member_requests", "member_request_events")
V3_TABLES = (*V2_TABLES, "assistant_escalations")
V4_TABLES = (*V3_TABLES, "portal_users", "assistant_support_replies", "portal_audit")
V5_TABLES = (*V4_TABLES, "education_video_posts")
V6_TABLES = (*V5_TABLES, "channel_history")
TABLES = (*V6_TABLES, "applicant_followup_state",
          "applicant_followup_deliveries", "applicant_followup_events")


def _archive_json_default(value):
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported archive value type: {type(value).__name__}")


def _archive_contract(db):
    if db.postgres:
        row = db.conn.execute("SELECT version FROM schema_version").fetchone()
        version = int(row[0]) if row else 0
    else:
        version = int(db.conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= 9:
        return 7, TABLES
    if version >= 6:
        return 6, V6_TABLES
    if version == 5:
        return 5, V5_TABLES
    if version == 4:
        return 4, V4_TABLES
    if version == 3:
        return 3, V3_TABLES
    if version == 2:
        return 2, V2_TABLES
    if version == 1:
        return 1, LEGACY_TABLES
    raise RuntimeError("Unsupported bot database schema version.")


def export_bundle(db, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    export_format, table_names = _archive_contract(db)
    with db.transaction():
        tables = {t: db.rows(f"SELECT * FROM {t}") for t in table_names}
        assets = db.rows("SELECT * FROM assets")
    manifest = {"format": export_format, "files": {}, "images": [], "videos": []}
    files = {"database.json": json.dumps(tables, default=_archive_json_default).encode()}
    for asset in assets:
        name = "images/" + asset["id"]
        files[name] = bytes(asset["content"])
        refs = []
        for table in ("drafts", "operations"):
            for row in tables[table]:
                obj = json.loads(row["data" if table == "drafts" else "payload"])
                for role in ("image", "original"):
                    if obj.get(role) == "asset:" + asset["id"]:
                        refs.append({"table": table, "id": row.get("id", row.get("owner")),
                                     "role": role, "trade_id": obj.get("trade", {}).get("id"),
                                     "kind": obj.get("kind", row.get("kind", "analysis"))})
        manifest["images"].append({"id": asset["id"], "references": refs})
    video_dir = Path(getattr(db, "education_video_data_dir", db.directory / "education-videos"))
    for video in tables.get("education_video_posts", []):
        if video["status"] == "awaiting_upload":
            continue
        name = str(video["storage_name"])
        if not __import__("re").fullmatch(r"[a-f0-9]{32}\.mp4", name):
            raise ValueError("Invalid educational video storage reference.")
        path_on_disk = video_dir / name
        if not path_on_disk.is_file():
            raise ValueError("An educational video is missing from persistent storage.")
        content = path_on_disk.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != int(video["byte_size"]) or digest != video["file_sha256"]:
            raise ValueError("Educational video integrity check failed.")
        archive_name = "videos/" + name
        files[archive_name] = content
        manifest["videos"].append({
            "video_id": video["id"],
            "storage_name": name,
            "sha256": digest,
        })
    for name, content in files.items():
        manifest["files"][name] = hashlib.sha256(content).hexdigest()
    temp = path.with_suffix(".partial")
    with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    temp.replace(path)
    path.chmod(0o600)
    return path


def restore_bundle(db, path):
    if db.postgres and not db.conn.execute("SELECT pg_try_advisory_lock(hashtext(current_schema()),8219442)").fetchone()[0]:
        raise ValueError("Stop the target worker before restoring.")
    target_format, target_tables = _archive_contract(db)
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        export_format = manifest["format"]
        if export_format not in (1, 2, 3, 4, 5, 6, 7):
            raise ValueError("Unsupported export version.")
        if export_format > target_format:
            raise ValueError("Target bot database schema is older than this export; apply its migration first.")
        files = {name: z.read(name) for name in manifest["files"]}
        if any(hashlib.sha256(content).hexdigest() != manifest["files"][name] for name, content in files.items()):
            raise ValueError("Export checksum mismatch.")
        tables = json.loads(files["database.json"])
        if export_format == 1:
            if set(tables) != set(LEGACY_TABLES):
                raise ValueError("Legacy export table set is incomplete.")
            tables["member_requests"] = []
            tables["member_request_events"] = []
            tables["assistant_escalations"] = []
            tables["portal_users"] = []
            tables["assistant_support_replies"] = []
            tables["portal_audit"] = []
        elif export_format == 2:
            if set(tables) != set(V2_TABLES):
                raise ValueError("Export table set is incomplete.")
            tables["assistant_escalations"] = []
            tables["portal_users"] = []
            tables["assistant_support_replies"] = []
            tables["portal_audit"] = []
        elif export_format == 3:
            if set(tables) != set(V3_TABLES):
                raise ValueError("Export table set is incomplete.")
            tables["portal_users"] = []
            tables["assistant_support_replies"] = []
            tables["portal_audit"] = []
        elif export_format == 4:
            if set(tables) != set(V4_TABLES):
                raise ValueError("Export table set is incomplete.")
        elif export_format == 5:
            if set(tables) != set(V5_TABLES):
                raise ValueError("Export table set is incomplete.")
        elif export_format == 6:
            if set(tables) != set(V6_TABLES):
                raise ValueError("Export table set is incomplete.")
        elif set(tables) != set(TABLES):
            raise ValueError("Export table set is incomplete.")
        if export_format < 5:
            tables["education_video_posts"] = []
        if export_format < 6:
            tables["channel_history"] = []
        if export_format < 7:
            tables["applicant_followup_state"] = []
            tables["applicant_followup_deliveries"] = []
            tables["applicant_followup_events"] = []
        assets = []
        for image in manifest["images"]:
            ident = image["id"]
            if not __import__("re").fullmatch(r"[a-f0-9]{64}\.(png|jpg|webp)", ident):
                raise ValueError("Invalid image manifest.")
            content = files["images/" + ident]
            if hashlib.sha256(content).hexdigest() != ident.split(".")[0]:
                raise ValueError("Image checksum mismatch.")
            assets.append((ident, content))
        video_manifest = manifest.get("videos", [])
        video_dir = Path(getattr(db, "education_video_data_dir", db.directory / "education-videos"))
        staged_videos = []
        for video_ref in video_manifest:
            name = str(video_ref.get("storage_name", ""))
            if not __import__("re").fullmatch(r"[a-f0-9]{32}\.mp4", name):
                raise ValueError("Invalid educational video manifest.")
            archive_name = "videos/" + name
            if archive_name not in files:
                raise ValueError("An educational video is missing from the export.")
            content = files[archive_name]
            if hashlib.sha256(content).hexdigest() != video_ref.get("sha256"):
                raise ValueError("Educational video checksum mismatch.")
            matches = [row for row in tables["education_video_posts"]
                       if row["id"] == video_ref.get("video_id")
                       and row["storage_name"] == name]
            if len(matches) != 1 or matches[0]["file_sha256"] != video_ref.get("sha256"):
                raise ValueError("Educational video manifest does not match its database record.")
            staged_videos.append((name, content))
        if len({name for name, _ in staged_videos}) != len(staged_videos):
            raise ValueError("Duplicate educational video storage reference.")
    video_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any((video_dir / name).exists() for name, _ in staged_videos):
        raise ValueError("Restore requires empty educational video storage; existing files are never overwritten.")
    moved_videos = []
    try:
        with db.transaction() as c:
            for table in (*target_tables, "portal_sessions", "assets"):
                if c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]:
                    raise ValueError("Restore requires an empty target; existing data is never overwritten.")
            for table in target_tables:
                allowed = {column.name for column in c.execute(f"SELECT * FROM {table} LIMIT 0").cursor.description} if db.postgres else {
                    row[1] for row in c.execute(f"PRAGMA table_info({table})")}
                for row in tables[table]:
                    if set(row) != allowed:
                        raise ValueError(f"Unexpected export columns in {table}.")
                    record = dict(row)
                    if db.postgres and table == "portal_users":
                        for column in ("active", "must_change_password"):
                            record[column] = bool(record[column])
                    columns = list(record)
                    c.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                              tuple(record[k] for k in columns))
            for ident, content in assets:
                c.execute("INSERT INTO assets VALUES (?,?)", (ident, content))
            for name, content in staged_videos:
                path_on_disk = video_dir / name
                with path_on_disk.open("xb") as output:
                    output.write(content)
                path_on_disk.chmod(0o600)
                moved_videos.append(path_on_disk)
            c.execute("UPDATE operations SET status='uncertain' WHERE status='sending'")
            c.execute("UPDATE assistant_support_replies SET status='uncertain' WHERE status='sending'")
            c.execute("UPDATE assistant_escalations SET status='reply_uncertain',updated=? "
                      "WHERE status='reply_sending'",
                      (datetime.now(timezone.utc).isoformat(timespec="microseconds"),))
            c.execute("UPDATE education_video_posts SET status='uncertain',safe_result=? "
                      "WHERE status IN ('queued','sending')",
                      ("Restored with an unresolved Telegram delivery; verify the group before any new post.",))
            # Old keyboards must never authorize new actions after a restore.
            c.execute("UPDATE buttons SET used=1")
            if db.postgres:
                for table in ("events", "errors", "member_request_events"):
                    c.execute(f"SELECT setval(pg_get_serial_sequence('{db.schema}.{table}','id'), COALESCE((SELECT MAX(id) FROM {table}),0)+1, false)")
    except Exception:
        for path_on_disk in moved_videos:
            path_on_disk.unlink(missing_ok=True)
        raise
    return {table: len(rows) for table, rows in tables.items()}
