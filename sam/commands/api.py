"""CLI command helpers for running the FastAPI service."""

from __future__ import annotations

import asyncio
import logging
import sys
from getpass import getpass

import uvicorn

from ..api import create_app

logger = logging.getLogger(__name__)


async def run_api_server(
    host: str, port: int, reload: bool = False, log_level: str = "info"
) -> int:
    """Launch the FastAPI server with uvicorn."""

    config = uvicorn.Config(  # type: ignore[arg-type]
        create_app,
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        factory=True,
    )
    server = uvicorn.Server(config)

    try:
        await server.serve()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("API server crashed: %s", exc)
        return 1

    return 0


async def create_api_user(username: str, password: str | None, *, is_admin: bool = False) -> int:
    if not username:
        print("❌ Username is required", file=sys.stderr)
        logger.error("Username is required")
        return 1

    if not password:
        pwd = getpass("Password: ")
        confirm = getpass("Confirm password: ")
        if pwd != confirm:
            print("❌ Passwords do not match", file=sys.stderr)
            logger.error("Passwords do not match")
            return 1
        password = pwd

    print(f"Creating user '{username}'...")
    logger.info("Creating user '%s'...", username)
    try:
        # Use direct database access to avoid connection pool issues
        from ..api.auth import hash_password
        from ..config.settings import Settings
        from ..api.utils import normalize_user_id
        from datetime import datetime, timezone
        import aiosqlite

        Settings.refresh_from_env()
        db_path = Settings.SAM_DB_PATH
        logger.debug("Database path: %s", db_path)

        normalized_username = username.strip().lower()

        if not normalized_username:
            logger.error("Username must not be empty")
            return 1

        user_id = normalize_user_id(normalized_username)
        logger.debug("Hashing password...")
        password_hash = hash_password(password)
        logger.debug("Password hashed successfully")
        created_at = datetime.now(timezone.utc).isoformat()

        # Direct database connection (bypass pool for CLI)
        print(f"Connecting to database: {db_path}")
        logger.debug("Connecting to database: %s", db_path)
        try:
            conn = await asyncio.wait_for(aiosqlite.connect(db_path, timeout=5.0), timeout=10.0)
            print("Database connected")
            logger.debug("Database connected")
        except asyncio.TimeoutError:
            print("❌ Database connection timed out after 10 seconds", file=sys.stderr)
            logger.error("Database connection timed out")
            return 1
        try:
            # Initialize table if needed
            print("Creating table if needed...")
            logger.debug("Creating table if needed...")
            await asyncio.wait_for(
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS api_users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE,
                        user_id TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        is_admin INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                """),
                timeout=5.0,
            )
            print("Table created")
            await asyncio.wait_for(
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_api_users_username ON api_users(username)"
                ),
                timeout=5.0,
            )
            print("Index created")
            await asyncio.wait_for(conn.commit(), timeout=5.0)
            print("Table initialized")
            logger.debug("Table initialized")

            # Check if user exists
            print("Checking if user exists...")
            logger.debug("Checking if user exists...")
            cursor = await asyncio.wait_for(
                conn.execute(
                    "SELECT 1 FROM api_users WHERE username = ? LIMIT 1", (normalized_username,)
                ),
                timeout=5.0,
            )
            if await cursor.fetchone():
                print(f"❌ User '{username}' already exists", file=sys.stderr)
                logger.error("User '%s' already exists", username)
                return 1

            # Create user
            print("Inserting user into database...")
            logger.debug("Inserting user into database...")
            await asyncio.wait_for(
                conn.execute(
                    """
                    INSERT INTO api_users (username, user_id, password_hash, is_admin, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (normalized_username, user_id, password_hash, int(is_admin), created_at),
                ),
                timeout=5.0,
            )
            print("User inserted, committing...")
            await asyncio.wait_for(conn.commit(), timeout=5.0)
            print("Committed")
            logger.debug("User inserted successfully")

            logger.info("Created API user '%s' (admin=%s)", username, is_admin)
            print(f"✅ Created API user '{username}' (admin={is_admin})")
            return 0
        except asyncio.TimeoutError as timeout_exc:
            print(f"❌ Database operation timed out: {timeout_exc}", file=sys.stderr)
            logger.error("Database operation timed out: %s", timeout_exc)
            return 1
        except Exception as db_exc:
            print(f"❌ Database error: {db_exc}", file=sys.stderr)
            logger.exception("Database error: %s", db_exc)
            raise
        finally:
            await conn.close()
            logger.debug("Database connection closed")
    except ValueError as exc:
        error_msg = str(exc)
        if "already exists" in error_msg.lower():
            print(f"❌ User '{username}' already exists", file=sys.stderr)
            logger.error("User '%s' already exists", username)
        else:
            print(f"❌ Invalid username or password: {error_msg}", file=sys.stderr)
            logger.error("Invalid username or password: %s", error_msg)
        return 1
    except Exception as exc:
        print(f"❌ Failed to create user: {exc}", file=sys.stderr)
        logger.exception("Failed to create user '%s': %s", username, exc)
        return 1


__all__ = ["create_api_user", "run_api_server"]
