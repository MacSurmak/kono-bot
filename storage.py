import os
import json
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import asdict, is_dataclass
import asyncpg
from loguru import logger

_POOL: Optional[asyncpg.Pool] = None


def normalize_item_name(name: str) -> str:
    """Removes non-breaking spaces and normalizes contiguous whitespace."""
    if not name:
        return ""
    return " ".join(name.replace("\xa0", " ").strip().split())


async def init_db() -> asyncpg.Pool:
    """Initializes PostgreSQL connection pool and executes idempotent DDL migrations."""
    global _POOL

    host = os.getenv("POSTGRES_HOST")
    if not host or not host.strip():
        raise RuntimeError("CRITICAL CONFIGURATION ERROR: 'POSTGRES_HOST' environment variable is not set.")

    port_str = os.getenv("POSTGRES_PORT")
    if not port_str or not port_str.strip():
        raise RuntimeError("CRITICAL CONFIGURATION ERROR: 'POSTGRES_PORT' environment variable is not set.")
    port = int(port_str)

    db = os.getenv("POSTGRES_DB")
    if not db or not db.strip():
        raise RuntimeError("CRITICAL CONFIGURATION ERROR: 'POSTGRES_DB' environment variable is not set.")

    user = os.getenv("POSTGRES_USER")
    if not user or not user.strip():
        raise RuntimeError("CRITICAL CONFIGURATION ERROR: 'POSTGRES_USER' environment variable is not set.")

    password = os.getenv("POSTGRES_PASSWORD")
    if not password or not password.strip():
        raise RuntimeError("CRITICAL CONFIGURATION ERROR: 'POSTGRES_PASSWORD' environment variable is not set.")

    logger.info(f"Connecting to PostgreSQL at {host}:{port}/{db}...")
    _POOL = await asyncpg.create_pool(
        host=host,
        port=port,
        database=db,
        user=user,
        password=password,
        min_size=2,
        max_size=10,
    )

    async with _POOL.acquire() as conn:
        async with conn.transaction():
            # 1. Telegram bot users with encrypted iiko credentials
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_users (
                    telegram_id BIGINT PRIMARY KEY,
                    username TEXT,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    iiko_login TEXT,
                    iiko_password_encrypted BYTEA,
                    default_store_id TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 2. Single-use invitation tokens
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_invites (
                    token TEXT PRIMARY KEY,
                    created_by BIGINT NOT NULL,
                    used_by BIGINT,
                    is_used BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    used_at TIMESTAMPTZ
                );
            """)

            # 3. User-connected restaurant delivery stores
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_stores (
                    user_id BIGINT NOT NULL,
                    store_id TEXT NOT NULL,
                    store_name TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, store_id)
                );
                CREATE INDEX IF NOT EXISTS idx_user_stores_user ON user_stores (user_id);
            """)

            # 4. Supplier mappings (network consensus)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS supplier_mappings (
                    id BIGSERIAL PRIMARY KEY,
                    supplier_id TEXT NOT NULL,
                    raw_name TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    iiko_name TEXT NOT NULL,
                    iiko_article TEXT,
                    usage_count INTEGER NOT NULL DEFAULT 1,
                    package_coefficient NUMERIC NOT NULL DEFAULT 1.0,
                    last_used_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(supplier_id, raw_name, product_id)
                );
                CREATE INDEX IF NOT EXISTS idx_supplier_mappings_lookup 
                ON supplier_mappings (supplier_id, raw_name);
            """)

            # 5. Mapping audit log for revocations and authorship tracking
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS mapping_audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    supplier_id TEXT NOT NULL,
                    raw_name TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    iiko_name TEXT NOT NULL,
                    package_coefficient NUMERIC NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_mapping_audit_user_created 
                ON mapping_audit_log (user_id, created_at DESC);
            """)

            # 6. Preferred supplier mappings for disambiguating identical INNs
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS preferred_suppliers (
                    inn TEXT PRIMARY KEY,
                    supplier_id TEXT NOT NULL,
                    supplier_name TEXT NOT NULL
                );
            """)

            # 7. Persistent document processing sessions
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS invoice_sessions (
                    doc_id TEXT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    state_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 8. Gemini API key rotation telemetry
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS gemini_key_stats (
                    key_name TEXT PRIMARY KEY,
                    total_requests INTEGER NOT NULL DEFAULT 0,
                    successful_requests INTEGER NOT NULL DEFAULT 0,
                    rate_limit_hits INTEGER NOT NULL DEFAULT 0,
                    last_used_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

    logger.info("PostgreSQL schema validated and initialized successfully.")
    return _POOL


async def close_db():
    """Gracefully terminates PostgreSQL connection pool."""
    global _POOL
    if _POOL:
        await _POOL.close()
        _POOL = None
        logger.info("PostgreSQL connection pool closed.")


def get_db_pool() -> asyncpg.Pool:
    """Returns active database pool with Fail-Fast invariant check."""
    if _POOL is None:
        raise RuntimeError(
            "Database pool is not initialized. Ensure 'await init_db()' ran on startup."
        )
    return _POOL


# ================= TELEGRAM ACCESS CONTROL REPOSITORY =================
async def get_bot_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    pool = get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT telegram_id, username, full_name, role, iiko_login, iiko_password_encrypted, default_store_id, is_active
        FROM bot_users WHERE telegram_id = $1
    """,
        telegram_id,
    )
    if not row:
        return None
    return dict(row)


async def upsert_bot_user(
    telegram_id: int, username: Optional[str], full_name: str, role: str = "user"
) -> None:
    pool = get_db_pool()
    await pool.execute(
        """
        INSERT INTO bot_users (telegram_id, username, full_name, role, is_active)
        VALUES ($1, $2, $3, $4, TRUE)
        ON CONFLICT (telegram_id) DO UPDATE SET
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name,
            role = EXCLUDED.role,
            is_active = TRUE;
    """,
        telegram_id,
        username,
        full_name,
        role,
    )


async def update_user_iiko_credentials(
    telegram_id: int, login: str, encrypted_password: bytes
) -> None:
    pool = get_db_pool()
    await pool.execute(
        """
        UPDATE bot_users 
        SET iiko_login = $2, iiko_password_encrypted = $3
        WHERE telegram_id = $1;
    """,
        telegram_id,
        login.strip(),
        encrypted_password,
    )


async def update_user_default_store(telegram_id: int, store_id: Optional[str]) -> None:
    pool = get_db_pool()
    await pool.execute(
        """
        UPDATE bot_users 
        SET default_store_id = $2
        WHERE telegram_id = $1;
    """,
        telegram_id,
        store_id,
    )


async def set_user_role(telegram_id: int, role: str) -> None:
    """Updates user authorization role in database."""
    pool = get_db_pool()
    await pool.execute(
        "UPDATE bot_users SET role = $2 WHERE telegram_id = $1;",
        telegram_id,
        role.strip(),
    )


async def set_user_active(telegram_id: int, is_active: bool) -> None:
    """Blocks or activates user access."""
    pool = get_db_pool()
    await pool.execute(
        "UPDATE bot_users SET is_active = $2 WHERE telegram_id = $1;",
        telegram_id,
        is_active,
    )


async def is_admin_user(telegram_id: int) -> bool:
    """Determines if user is an administrator via primary config or active DB role."""
    from config import get_admin_ids

    # Primary bootstrap admin from config.yaml is permanently privileged
    if telegram_id in get_admin_ids():
        return True

    pool = get_db_pool()
    row = await pool.fetchrow(
        "SELECT role, is_active FROM bot_users WHERE telegram_id = $1;",
        telegram_id,
    )
    if not row:
        return False
    return row["role"] == "admin" and bool(row["is_active"])


async def get_all_bot_users() -> List[Dict[str, Any]]:
    pool = get_db_pool()
    rows = await pool.fetch("""
        SELECT telegram_id, username, full_name, role, iiko_login, default_store_id, is_active, created_at
        FROM bot_users ORDER BY created_at ASC;
    """)
    return [dict(r) for r in rows]


async def get_all_bot_users_paginated(
    offset: int = 0, limit: int = 6
) -> Tuple[List[Dict[str, Any]], int]:
    """Retrieves paginated employee list along with total count."""
    pool = get_db_pool()
    total = await pool.fetchval("SELECT COUNT(*) FROM bot_users;")
    rows = await pool.fetch(
        """
        SELECT telegram_id, username, full_name, role, iiko_login, default_store_id, is_active, created_at
        FROM bot_users ORDER BY created_at ASC
        OFFSET $1 LIMIT $2;
    """,
        offset,
        limit,
    )
    return [dict(r) for r in rows], total or 0


async def create_invite_token(created_by: int) -> str:
    import secrets

    token = secrets.token_urlsafe(16)
    pool = get_db_pool()
    await pool.execute(
        """
        INSERT INTO bot_invites (token, created_by, is_used)
        VALUES ($1, $2, FALSE);
    """,
        token,
        created_by,
    )
    return token


async def validate_and_consume_invite(
    token: str, telegram_id: int, username: Optional[str], full_name: str
) -> bool:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT token, is_used FROM bot_invites WHERE token = $1 FOR UPDATE;",
                token,
            )
            if not row or row["is_used"]:
                return False

            await conn.execute(
                """
                UPDATE bot_invites 
                SET is_used = TRUE, used_by = $2, used_at = CURRENT_TIMESTAMP 
                WHERE token = $1;
            """,
                token,
                telegram_id,
            )

            await conn.execute(
                """
                INSERT INTO bot_users (telegram_id, username, full_name, role, is_active)
                VALUES ($1, $2, $3, 'operator', TRUE)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    full_name = EXCLUDED.full_name,
                    is_active = TRUE;
            """,
                telegram_id,
                username,
                full_name,
            )
            return True


# ================= USER STORES REPOSITORY =================
async def get_user_stores(user_id: int) -> List[Dict[str, str]]:
    """Retrieves all restaurant stores connected to specific operator profile."""
    pool = get_db_pool()
    rows = await pool.fetch(
        "SELECT store_id, store_name FROM user_stores WHERE user_id = $1 ORDER BY store_name ASC;",
        user_id,
    )
    return [{"store_id": r["store_id"], "name": r["store_name"]} for r in rows]


async def toggle_user_store(user_id: int, store_id: str, store_name: str) -> bool:
    """Connects or disconnects a restaurant store for user. Returns True if connected, False if disconnected."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM user_stores WHERE user_id = $1 AND store_id = $2;",
            user_id,
            store_id,
        )
        if row:
            await conn.execute(
                "DELETE FROM user_stores WHERE user_id = $1 AND store_id = $2;",
                user_id,
                store_id,
            )
            return False
        else:
            await conn.execute(
                "INSERT INTO user_stores (user_id, store_id, store_name) VALUES ($1, $2, $3);",
                user_id,
                store_id,
                store_name,
            )
            return True


# ================= MAPPINGS, CONSENSUS & GOVERNANCE =================
async def record_mapping_vote(
    supplier_id: str,
    raw_name: str,
    product_id: str,
    iiko_name: str,
    article: str = "",
    weight: int = 1,
    package_coefficient: float = 1.0,
    user_id: Optional[int] = None,
    source: str = "manual",
) -> None:
    clean_name = normalize_item_name(raw_name)
    safe_coeff = (
        float(package_coefficient)
        if package_coefficient and package_coefficient > 0
        else 1.0
    )

    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Update network consensus
            await conn.execute(
                """
                INSERT INTO supplier_mappings 
                (supplier_id, raw_name, product_id, iiko_name, iiko_article, usage_count, package_coefficient, last_used_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, CURRENT_TIMESTAMP)
                ON CONFLICT (supplier_id, raw_name, product_id) DO UPDATE SET 
                    usage_count = supplier_mappings.usage_count + EXCLUDED.usage_count,
                    package_coefficient = EXCLUDED.package_coefficient,
                    last_used_at = CURRENT_TIMESTAMP;
            """,
                supplier_id,
                clean_name,
                product_id,
                iiko_name,
                article,
                weight,
                safe_coeff,
            )

            # Record authorship in audit ledger
            if user_id:
                await conn.execute(
                    """
                    INSERT INTO mapping_audit_log 
                    (user_id, supplier_id, raw_name, product_id, iiko_name, package_coefficient, source)
                    VALUES ($1, $2, $3, $4, $5, $6, $7);
                """,
                    user_id,
                    supplier_id,
                    clean_name,
                    product_id,
                    iiko_name,
                    safe_coeff,
                    source,
                )


async def get_consensus_mapping(
    supplier_id: str, raw_name: str
) -> Optional[Dict[str, Any]]:
    clean_name = normalize_item_name(raw_name)
    pool = get_db_pool()
    rows = await pool.fetch(
        """
        SELECT product_id, iiko_name, iiko_article, usage_count, package_coefficient
        FROM supplier_mappings
        WHERE supplier_id = $1 AND raw_name = $2
        ORDER BY usage_count DESC, last_used_at DESC;
    """,
        supplier_id,
        clean_name,
    )
    if not rows:
        return None

    total_votes = sum(r["usage_count"] for r in rows)
    winner = rows[0]
    confidence = winner["usage_count"] / total_votes
    coeff = (
        float(winner["package_coefficient"]) if winner["package_coefficient"] else 1.0
    )

    return {
        "product_id": winner["product_id"],
        "iiko_name": winner["iiko_name"],
        "iiko_article": winner["iiko_article"],
        "votes": winner["usage_count"],
        "package_coefficient": coeff,
        "total_votes": total_votes,
        "confidence": confidence,
        "has_conflict": len(rows) > 1 and confidence < 0.75,
        "all_variants": [dict(r) for r in rows],
    }


async def get_user_mappings(
    user_id: int, offset: int = 0, limit: int = 6
) -> Tuple[List[Dict[str, Any]], int]:
    """Returns all mappings authored by specific operator with pagination support."""
    pool = get_db_pool()
    total = await pool.fetchval(
        "SELECT COUNT(*) FROM mapping_audit_log WHERE user_id = $1;",
        user_id,
    )
    rows = await pool.fetch(
        """
        SELECT id, supplier_id, raw_name, product_id, iiko_name, package_coefficient, created_at
        FROM mapping_audit_log
        WHERE user_id = $1
        ORDER BY created_at DESC
        OFFSET $2 LIMIT $3;
    """,
        user_id,
        offset,
        limit,
    )
    return [dict(r) for r in rows], total or 0


async def revoke_user_mapping(user_id: int, audit_log_id: int) -> bool:
    """Revokes specific operator vote, decrementing usage or purging mapping if sole author."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            audit_entry = await conn.fetchrow(
                "SELECT * FROM mapping_audit_log WHERE id = $1 AND user_id = $2 FOR UPDATE;",
                audit_log_id,
                user_id,
            )
            if not audit_entry:
                return False

            supplier_id = audit_entry["supplier_id"]
            raw_name = audit_entry["raw_name"]
            product_id = audit_entry["product_id"]

            mapping = await conn.fetchrow(
                """
                SELECT id, usage_count 
                FROM supplier_mappings 
                WHERE supplier_id = $1 AND raw_name = $2 AND product_id = $3 
                FOR UPDATE;
            """,
                supplier_id,
                raw_name,
                product_id,
            )

            if mapping:
                if mapping["usage_count"] <= 1:
                    await conn.execute(
                        "DELETE FROM supplier_mappings WHERE id = $1;", mapping["id"]
                    )
                else:
                    await conn.execute(
                        "UPDATE supplier_mappings SET usage_count = usage_count - 1 WHERE id = $1;",
                        mapping["id"],
                    )

            await conn.execute(
                "DELETE FROM mapping_audit_log WHERE id = $1;", audit_log_id
            )
            return True


async def search_mappings_for_admin_paginated(
    query: str, offset: int = 0, limit: int = 6
) -> Tuple[List[Dict[str, Any]], int]:
    """Searches knowledge base mappings with pagination."""
    pool = get_db_pool()
    like_pattern = f"%{query.strip().lower()}%"
    total = await pool.fetchval(
        """
        SELECT COUNT(*) FROM supplier_mappings
        WHERE LOWER(raw_name) LIKE $1 OR LOWER(iiko_name) LIKE $1 OR LOWER(COALESCE(iiko_article, '')) LIKE $1;
    """,
        like_pattern,
    )
    rows = await pool.fetch(
        """
        SELECT id, raw_name, iiko_name, iiko_article, usage_count, package_coefficient
        FROM supplier_mappings
        WHERE LOWER(raw_name) LIKE $1 OR LOWER(iiko_name) LIKE $1 OR LOWER(COALESCE(iiko_article, '')) LIKE $1
        ORDER BY usage_count DESC
        OFFSET $2 LIMIT $3;
    """,
        like_pattern,
        offset,
        limit,
    )
    results = [
        {
            "id": r["id"],
            "raw_name": r["raw_name"],
            "iiko_name": r["iiko_name"],
            "article": r["iiko_article"] or "",
            "usage_count": r["usage_count"],
            "coefficient": float(r["package_coefficient"]),
        }
        for r in rows
    ]
    return results, total or 0


async def search_mappings_for_admin(
    query: str, limit: int = 10
) -> List[Dict[str, Any]]:
    """Backward-compatible unpaginated search query."""
    results, _ = await search_mappings_for_admin_paginated(query, offset=0, limit=limit)
    return results


async def get_user_recent_mappings(
    user_id: int, limit: int = 10
) -> List[Dict[str, Any]]:
    """Backward-compatible helper returning recent user mappings."""
    mappings, _ = await get_user_mappings(user_id, offset=0, limit=limit)
    return mappings


async def delete_mapping_by_id(mapping_id: int) -> bool:
    pool = get_db_pool()
    res = await pool.execute("DELETE FROM supplier_mappings WHERE id = $1;", mapping_id)
    return "DELETE 1" in res


# ================= PREFERRED SUPPLIERS =================
async def save_preferred_supplier(
    inn: str, supplier_id: str, supplier_name: str
) -> None:
    pool = get_db_pool()
    await pool.execute(
        """
        INSERT INTO preferred_suppliers (inn, supplier_id, supplier_name)
        VALUES ($1, $2, $3)
        ON CONFLICT (inn) DO UPDATE SET 
            supplier_id = EXCLUDED.supplier_id,
            supplier_name = EXCLUDED.supplier_name;
    """,
        inn.strip(),
        supplier_id.strip(),
        supplier_name.strip(),
    )


async def get_preferred_supplier(inn: str) -> Optional[Tuple[str, str]]:
    pool = get_db_pool()
    row = await pool.fetchrow(
        "SELECT supplier_id, supplier_name FROM preferred_suppliers WHERE inn = $1;",
        inn.strip(),
    )
    if not row:
        return None
    return (row["supplier_id"], row["supplier_name"])


# ================= INVOICE PERSISTENT SESSIONS =================
async def save_invoice_session(
    doc_id: str, user_id: int, state: Dict[str, Any]
) -> None:
    def default_serializer(o):
        if is_dataclass(o):
            return asdict(o)
        raise TypeError(f"Object of type {type(o)} is not JSON serializable")

    state_json = json.dumps(state, default=default_serializer, ensure_ascii=False)
    pool = get_db_pool()
    await pool.execute(
        """
        INSERT INTO invoice_sessions (doc_id, user_id, state_json, updated_at)
        VALUES ($1, $2, $3::jsonb, CURRENT_TIMESTAMP)
        ON CONFLICT (doc_id) DO UPDATE SET
            state_json = EXCLUDED.state_json,
            updated_at = CURRENT_TIMESTAMP;
    """,
        doc_id,
        user_id,
        state_json,
    )


async def get_invoice_session(doc_id: str) -> Optional[Dict[str, Any]]:
    pool = get_db_pool()
    row = await pool.fetchrow(
        "SELECT state_json FROM invoice_sessions WHERE doc_id = $1;", doc_id
    )
    if not row:
        return None
    val = row["state_json"]
    return json.loads(val) if isinstance(val, str) else val


async def delete_invoice_session(doc_id: str) -> None:
    pool = get_db_pool()
    await pool.execute("DELETE FROM invoice_sessions WHERE doc_id = $1;", doc_id)


async def cleanup_stale_sessions(ttl_seconds: int = 3600) -> List[str]:
    pool = get_db_pool()
    rows = await pool.fetch(
        """
        DELETE FROM invoice_sessions 
        WHERE updated_at < NOW() - ($1 || ' seconds')::INTERVAL
        RETURNING doc_id;
    """,
        str(ttl_seconds),
    )
    return [r["doc_id"] for r in rows]


# ================= GEMINI TELEMETRY =================
async def record_gemini_key_stat(
    key_name: str, success: bool, is_rate_limit: bool = False
) -> None:
    pool = get_db_pool()
    await pool.execute(
        """
        INSERT INTO gemini_key_stats (key_name, total_requests, successful_requests, rate_limit_hits, last_used_at)
        VALUES ($1, 1, $2, $3, CURRENT_TIMESTAMP)
        ON CONFLICT (key_name) DO UPDATE SET
            total_requests = gemini_key_stats.total_requests + 1,
            successful_requests = gemini_key_stats.successful_requests + $2,
            rate_limit_hits = gemini_key_stats.rate_limit_hits + $3,
            last_used_at = CURRENT_TIMESTAMP;
    """,
        key_name,
        1 if success else 0,
        1 if is_rate_limit else 0,
    )


async def get_gemini_key_usage_counts() -> Dict[str, int]:
    pool = get_db_pool()
    rows = await pool.fetch("SELECT key_name, total_requests FROM gemini_key_stats;")
    return {r["key_name"]: r["total_requests"] for r in rows}


async def get_all_gemini_key_stats() -> List[Tuple[str, int, int, int, str]]:
    pool = get_db_pool()
    rows = await pool.fetch("""
        SELECT key_name, total_requests, successful_requests, rate_limit_hits, to_char(last_used_at, 'YYYY-MM-DD HH24:MI:SS') as last_used
        FROM gemini_key_stats
        ORDER BY total_requests DESC;
    """)
    return [
        (
            r["key_name"],
            r["total_requests"],
            r["successful_requests"],
            r["rate_limit_hits"],
            r["last_used"],
        )
        for r in rows
    ]
