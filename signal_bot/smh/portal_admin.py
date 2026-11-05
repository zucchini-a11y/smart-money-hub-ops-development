"""Bootstrap or recover the first support-portal administrator on PostgreSQL."""
import argparse
import getpass
import hashlib
import os
import re
import secrets
import sys
import uuid
from datetime import datetime, timezone


def password_hash(password):
    salt = os.urandom(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=64)
    return f"scrypt$16384$8$1${salt.hex()}${derived.hex()}"


def _validated_email(value):
    email = value.strip().lower()
    if not re.fullmatch(r"[^@\s]{1,128}@[^@\s]{1,120}\.[^@\s]{2,}", email):
        raise ValueError("Enter a valid staff email.")
    return email


def _hidden_password(prompt):
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError("This Shell cannot securely hide password input. No database changes were made.")
    return getpass.getpass(prompt)


def create_admin_account(url, email, display_name, password, *, must_change_password, connect=None):
    if connect is None:
        import psycopg
        connect = psycopg.connect

    encoded = password_hash(password)
    stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with connect(url) as conn:
        conn.execute("SET search_path TO smh")
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()),8219443)")
            version = conn.execute("SELECT version FROM schema_version").fetchone()
            if not version or int(version[0]) not in (5, 6, 7, 8):
                raise ValueError("The support-portal database migration is not ready.")
            existing = conn.execute("SELECT count(*) FROM portal_users").fetchone()[0]
            if existing:
                raise ValueError("A portal account already exists. An administrator must add staff.")
            conn.execute(
                "INSERT INTO portal_users "
                "(id,email,display_name,password_hash,role,active,must_change_password,created,updated) "
                "VALUES (%s,%s,%s,%s,'admin',TRUE,%s,%s,%s)",
                (uuid.uuid4().hex, email, display_name, encoded, must_change_password, stamp, stamp),
            )
            conn.execute(
                "INSERT INTO portal_audit(id,actor_id,action,entity_id,created,detail) "
                "VALUES(%s,NULL,%s,%s,%s,%s)",
                (uuid.uuid4().hex, "bootstrap_admin_created", email, stamp,
                 "Created by the Development setup command."),
            )


def setup_development(input_fn=None, password_fn=None, create_fn=None):
    input_fn = input_fn or input
    password_fn = password_fn or _hidden_password
    create_fn = create_fn or create_admin_account

    if os.getenv("SMH_ISOLATED_TEST_INSTANCE", "false").lower() == "true":
        raise ValueError("Run this from the project's Development Shell, not the isolated test bot.")
    if os.getenv("NODE_ENV", "").lower() == "production":
        raise ValueError("Run this from the Development Shell, not Production.")
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("The Development database is not available in this Shell.")

    print("This creates the first support-portal admin in Development only.")
    print("Continue only if Replit's Database pane is set to Development.")
    if input_fn("Type DEVELOPMENT to continue: ").strip() != "DEVELOPMENT":
        print("Cancelled. No database changes were made.")
        return False

    email = _validated_email(input_fn("Portal admin email: "))
    display_name = input_fn("Name shown in the portal: ").strip()
    if not display_name:
        raise ValueError("Enter the name to show in the portal.")

    password = password_fn("Choose a password (at least 12 characters): ")
    repeated_password = password_fn("Type the same password again: ")
    if len(password) < 12:
        raise ValueError("Choose a password with at least 12 characters.")
    if password != repeated_password:
        raise ValueError("The passwords did not match. No database changes were made.")

    create_fn(url, email, display_name, password, must_change_password=False)
    print("Portal administrator created in Development. Your password was not displayed.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup-dev", "create-admin", "reset-admin"))
    parser.add_argument("--email")
    parser.add_argument("--display-name", default="")
    parser.add_argument("--confirm-database-target", action="store_true",
                        help="Confirm this is the intended PostgreSQL database.")
    args = parser.parse_args()
    if args.command == "setup-dev":
        setup_development()
        return
    if not args.confirm_database_target:
        raise ValueError("Refusing to write until --confirm-database-target is provided.")
    if os.getenv("SMH_ISOLATED_TEST_INSTANCE", "false").lower() == "true":
        raise ValueError("This account tool is only for the chosen PostgreSQL portal database.")
    if not args.email:
        raise ValueError("--email is required.")
    email = _validated_email(args.email)
    if args.command == "create-admin" and not args.display_name.strip():
        raise ValueError("--display-name is required when creating the first administrator.")
    url = os.getenv("SMH_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Set SMH_DATABASE_URL or DATABASE_URL for the intended PostgreSQL database.")

    import psycopg
    password = secrets.token_urlsafe(18)
    encoded = password_hash(password)
    stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with psycopg.connect(url) as conn:
        conn.execute("SET search_path TO smh")
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()),8219443)")
            version = conn.execute("SELECT version FROM schema_version").fetchone()
            if not version or int(version[0]) not in (5, 6, 7, 8):
                raise ValueError("Apply the support-portal database migration before provisioning an account.")
            if args.command == "create-admin":
                existing = conn.execute("SELECT count(*) FROM portal_users").fetchone()[0]
                if existing:
                    raise ValueError("Portal accounts already exist. An active administrator must create staff.")
                conn.execute(
                    "INSERT INTO portal_users "
                    "(id,email,display_name,password_hash,role,active,must_change_password,created,updated) "
                    "VALUES (%s,%s,%s,%s,'admin',TRUE,TRUE,%s,%s)",
                    (uuid.uuid4().hex, email, args.display_name.strip(), encoded, stamp, stamp),
                )
                action = "bootstrap_admin_created"
            else:
                row = conn.execute("SELECT id FROM portal_users WHERE lower(email)=%s FOR UPDATE",
                                   (email,)).fetchone()
                if not row:
                    raise ValueError("No portal account exists for that email.")
                conn.execute(
                    "UPDATE portal_users SET password_hash=%s,role='admin',active=TRUE,"
                    "must_change_password=TRUE,updated=%s WHERE id=%s",
                    (encoded, stamp, row[0]),
                )
                conn.execute("DELETE FROM portal_sessions WHERE staff_id=%s", (row[0],))
                action = "admin_password_reset"
            actor = row[0] if args.command == "reset-admin" else None
            conn.execute(
                "INSERT INTO portal_audit(id,actor_id,action,entity_id,created,detail) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (uuid.uuid4().hex, actor, action, email, stamp, "Created or reset by the database operator."),
            )
    print("Temporary administrator password (shown once):")
    print(password)
    print("Sign in over HTTPS and change it immediately. Store it securely; it is not recoverable later.")


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(f"Setup stopped: {exc}")
        raise SystemExit(1) from None
    except Exception as exc:
        print(f"Portal account operation failed ({type(exc).__name__}); no credentials were displayed.")
        raise SystemExit(1) from None
