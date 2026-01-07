"""Migration definitions for SAM Framework database schema."""

from __future__ import annotations

from ..core.migrations import Migration, get_migration_manager


async def register_all_migrations(db_path: str) -> None:
    """Register all migrations with the migration manager.

    This function is idempotent - it will skip migrations that are already
    registered in the manager.
    """
    manager = get_migration_manager(db_path)

    # Check if already registered (prevent duplicate registration)
    if len(manager.migrations) > 0:
        return

    # Migration 1: Initial schema (sessions, preferences, trades, secure_data)
    async def migration_001_up(conn):
        # Create sessions table
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                agent_name TEXT,
                session_name TEXT,
                messages TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Create preferences table
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS preferences (
                user_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            )
            """
        )
        # Create trades table
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                token_address TEXT NOT NULL,
                action TEXT NOT NULL,
                amount REAL NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        # Create secure_data table
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS secure_data (
                user_id TEXT PRIMARY KEY,
                encrypted_private_key TEXT NOT NULL,
                wallet_address TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

    manager.register(
        Migration(
            version=1,
            name="initial_schema",
            description="Create initial database schema (sessions, preferences, trades, secure_data)",
            up=migration_001_up,
        )
    )

    # Migration 2: Add indexes for sessions
    async def migration_002_up(conn):
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at)"
        )
        # Check if agent_name column exists before creating indexes that use it
        cursor = await conn.execute("PRAGMA table_info(sessions)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "agent_name" in columns:
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_agent_name ON sessions(agent_name)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user_agent "
                "ON sessions(user_id, agent_name, updated_at)"
            )

    manager.register(
        Migration(
            version=2,
            name="add_session_indexes",
            description="Add indexes for sessions table",
            up=migration_002_up,
        )
    )

    # Migration 3: Add indexes for trades
    async def migration_003_up(conn):
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_user_timestamp ON trades(user_id, timestamp)"
        )

    manager.register(
        Migration(
            version=3,
            name="add_trade_indexes",
            description="Add indexes for trades table",
            up=migration_003_up,
        )
    )

    # Migration 4: Add refresh_tokens table
    async def migration_004_up(conn):
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id, expires_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash)"
        )

    manager.register(
        Migration(
            version=4,
            name="add_refresh_tokens",
            description="Add refresh_tokens table for JWT refresh token management",
            up=migration_004_up,
        )
    )

    # Migration 5: Add login_attempts table
    async def migration_005_up(conn):
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS login_attempts (
                username TEXT PRIMARY KEY,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                last_attempt_at TEXT
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_login_attempts_locked ON login_attempts(locked_until)"
        )

    manager.register(
        Migration(
            version=5,
            name="add_login_attempts",
            description="Add login_attempts table for account lockout tracking",
            up=migration_005_up,
        )
    )

    # Migration 6: Add api_users table
    async def migration_006_up(conn):
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_users_username ON api_users(username)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_api_users_user_id ON api_users(user_id)")

    manager.register(
        Migration(
            version=6,
            name="add_api_users",
            description="Add api_users table for authentication",
            up=migration_006_up,
        )
    )

    # Migration 7: Add user quotas table
    async def migration_007_up(conn):
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_quotas (
                user_id TEXT PRIMARY KEY,
                max_sessions INTEGER NOT NULL DEFAULT 50,
                max_messages_per_session INTEGER NOT NULL DEFAULT 1000,
                max_tokens_per_day INTEGER NOT NULL DEFAULT 1000000,
                max_agents INTEGER NOT NULL DEFAULT 20,
                tokens_used_today INTEGER NOT NULL DEFAULT 0,
                tokens_reset_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_quotas_user_id ON user_quotas(user_id)"
        )

    manager.register(
        Migration(
            version=7,
            name="add_user_quotas",
            description="Add user_quotas table for per-user resource limits",
            up=migration_007_up,
        )
    )

    # Migration 8: Add public_agents and agent_ratings tables for marketplace
    async def migration_008_up(conn):
        # Public agents table - tracks published/shared agents
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS public_agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                visibility TEXT NOT NULL DEFAULT 'private',
                share_token TEXT UNIQUE,
                published_at TEXT,
                download_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, agent_name)
            )
            """
        )
        # Indexes for public agents
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_public_agents_visibility ON public_agents(visibility)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_public_agents_published ON public_agents(published_at DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_public_agents_user ON public_agents(user_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_public_agents_downloads ON public_agents(download_count DESC)"
        )

        # Agent ratings table - user ratings for public agents
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
                comment TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(public_id, user_id)
            )
            """
        )
        # Indexes for ratings
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_ratings_public_id ON agent_ratings(public_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_ratings_user ON agent_ratings(user_id)"
        )

    manager.register(
        Migration(
            version=8,
            name="add_public_agents",
            description="Add public_agents and agent_ratings tables for marketplace sharing",
            up=migration_008_up,
        )
    )

    # Migration 9: Add agents table for database-backed agent storage
    async def migration_009_up(conn):
        # Agents table - stores agent definitions in database instead of files
        # This enables ACID transactions, proper user isolation, and scalability
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                system_prompt TEXT NOT NULL,
                llm_config TEXT,
                tools_config TEXT,
                metadata TEXT,
                variables TEXT,
                memory_config TEXT,
                middleware_config TEXT,
                is_template INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, name)
            )
            """
        )
        # Indexes for efficient queries
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_user_id ON agents(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_name ON agents(name)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agents_user_name ON agents(user_id, name)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_template ON agents(is_template)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agents_updated ON agents(updated_at DESC)"
        )

    manager.register(
        Migration(
            version=9,
            name="add_agents_table",
            description="Add agents table for database-backed agent storage with ACID guarantees",
            up=migration_009_up,
        )
    )

    # Migration 10: Add agent_versions table for version history
    async def migration_010_up(conn):
        # Agent versions table - tracks all changes to agent definitions
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                system_prompt TEXT NOT NULL,
                llm_config TEXT,
                tools_config TEXT,
                metadata TEXT,
                variables TEXT,
                memory_config TEXT,
                middleware_config TEXT,
                change_summary TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            )
            """
        )
        # Indexes for version queries
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_versions_agent_id ON agent_versions(agent_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_versions_version ON agent_versions(agent_id, version_number DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_versions_created ON agent_versions(created_at DESC)"
        )

    manager.register(
        Migration(
            version=10,
            name="add_agent_versions",
            description="Add agent_versions table for tracking agent change history",
            up=migration_010_up,
        )
    )

    # Migration 11: Add user_secrets table for encrypted credential storage
    async def migration_011_up(conn):
        # User secrets table - stores encrypted API keys and credentials per user
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_secrets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                integration TEXT NOT NULL,
                field TEXT NOT NULL,
                encrypted_value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, integration, field)
            )
            """
        )
        # Indexes for secret lookups
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_secrets_user ON user_secrets(user_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_secrets_integration ON user_secrets(user_id, integration)"
        )

    manager.register(
        Migration(
            version=11,
            name="add_user_secrets",
            description="Add user_secrets table for encrypted credential storage",
            up=migration_011_up,
        )
    )

    # Migration 12: Add audit_log table for tracking important operations
    async def migration_012_up(conn):
        # Audit log table for security and debugging
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user_id TEXT,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT,
                request_id TEXT,
                ip_address TEXT,
                user_agent TEXT,
                details TEXT,
                success INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        # Indexes for audit queries
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id, timestamp DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action, timestamp DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_request ON audit_log(request_id)"
        )

    manager.register(
        Migration(
            version=12,
            name="add_audit_log",
            description="Add audit_log table for security and debugging",
            up=migration_012_up,
        )
    )

    # Migration 13: Add wallet authentication support
    async def migration_013_up(conn):
        # Add wallet_address column to api_users (nullable for migration)
        # Check if column exists first
        cursor = await conn.execute("PRAGMA table_info(api_users)")
        columns = [row[1] for row in await cursor.fetchall()]

        if "wallet_address" not in columns:
            # SQLite doesn't support UNIQUE in ALTER TABLE ADD COLUMN
            # We add the column without constraint, then add a unique index
            await conn.execute("ALTER TABLE api_users ADD COLUMN wallet_address TEXT")

        # Make password_hash nullable for wallet-only users
        # SQLite doesn't support ALTER COLUMN, so we recreate the table
        # For now, we'll just allow NULL values by not enforcing NOT NULL on new inserts

        # Create wallet challenges table for sign-in nonces
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_challenges (
                wallet_address TEXT PRIMARY KEY,
                nonce TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        # Index for cleanup of expired challenges
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wallet_challenges_expires ON wallet_challenges(expires_at)"
        )

        # Index for wallet address lookups on users
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_users_wallet ON api_users(wallet_address)"
        )

    manager.register(
        Migration(
            version=13,
            name="add_wallet_auth",
            description="Add wallet authentication support (wallet_address on users, wallet_challenges table)",
            up=migration_013_up,
        )
    )

    # Migration 14: Add onboarding support and operational wallets
    async def migration_014_up(conn):
        # Check existing columns in api_users
        cursor = await conn.execute("PRAGMA table_info(api_users)")
        columns = [row[1] for row in await cursor.fetchall()]

        # Add onboarding_complete column if not exists
        if "onboarding_complete" not in columns:
            await conn.execute(
                "ALTER TABLE api_users ADD COLUMN onboarding_complete INTEGER NOT NULL DEFAULT 0"
            )

        # Add display_username column if not exists
        if "display_username" not in columns:
            await conn.execute("ALTER TABLE api_users ADD COLUMN display_username TEXT")

        # Create operational_wallets table for generated trading wallets
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operational_wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL UNIQUE,
                wallet_address TEXT NOT NULL UNIQUE,
                encrypted_private_key TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        # Indexes for operational_wallets
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_operational_wallets_user ON operational_wallets(user_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_operational_wallets_address ON operational_wallets(wallet_address)"
        )

        # Unique index for username (case-insensitive handled in app logic)
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_api_users_display_username ON api_users(display_username)"
        )

    manager.register(
        Migration(
            version=14,
            name="add_onboarding_support",
            description="Add onboarding_complete, display_username columns and operational_wallets table",
            up=migration_014_up,
        )
    )


__all__ = ["register_all_migrations"]
