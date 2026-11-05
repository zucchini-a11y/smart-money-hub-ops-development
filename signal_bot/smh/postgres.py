"""Small DB-API compatibility boundary; no provider-specific APIs."""
import re
import psycopg
from psycopg.rows import dict_row


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = cursor.rowcount

    def fetchone(self):
        r = self.cursor.fetchone()
        return Row(r) if r else None

    def fetchall(self):
        return [Row(r) for r in self.cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    def __init__(self, url, schema="smh"):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", schema):
            raise ValueError("Invalid schema.")
        self.raw = psycopg.connect(url, autocommit=True, row_factory=dict_row, connect_timeout=10)
        self.raw.execute(f"SET search_path TO {schema}")
        self.raw.execute("SET statement_timeout TO '30s'")

    def execute(self, sql, args=()):
        sql = sql.replace("?", "%s")
        sql = re.sub(r"json_extract\(data,'\$\.(\w+)'\)", r"(data::jsonb->>'\1')", sql)
        if sql.startswith("INSERT OR REPLACE INTO"):
            table = sql.split()[4]
            columns = {"kv": ["key", "value"], "drafts": ["owner", "data", "updated"],
                       "applications": ["user_id", "answers", "status", "updated"],
                       "access": ["user_id", "channel", "status", "updated"]}[table]
            keys = columns[:2] if table == "access" else columns[:1]
            sql = sql.replace("INSERT OR REPLACE", "INSERT") + " ON CONFLICT (" + ",".join(keys) + ") DO UPDATE SET " + ",".join(f"{c}=EXCLUDED.{c}" for c in columns if c not in keys)
        if sql.startswith("INSERT OR IGNORE"):
            sql = sql.replace("INSERT OR IGNORE", "INSERT") + " ON CONFLICT DO NOTHING"
        return Cursor(self.raw.execute(sql, args))

    def close(self):
        self.raw.close()

    def __enter__(self):
        self.tx = self.raw.transaction()
        self.tx.__enter__()
        self.raw.execute("SELECT pg_advisory_xact_lock(8219441)")
        return self

    def __exit__(self, *args):
        return self.tx.__exit__(*args)
