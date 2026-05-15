"""
migrations/add_memory_tables.py

Manuel migration — Alembic kullanmıyorsan doğrudan psql ile çalıştır.
Alembic kullanıyorsan: alembic revision --autogenerate -m "add_memory_tables"
"""

# ── Alembic migration (otomatik üretilmiş şablona göre düzenle) ───────────────

# revision identifiers
revision = "0002_add_memory_tables"
down_revision = "0001_initial"  # mevcut son migration'ının revision ID'si
branch_labels = None
depends_on = None


def upgrade(op=None):
    """
    Alembic op nesnesi verilmezse ham SQL olarak çalıştır.
    """
    statements = [
        # ── chat_room_memory tablosu ───────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS chat_room_memory (
            id                      SERIAL PRIMARY KEY,
            conversation_id         INTEGER NOT NULL UNIQUE
                                    REFERENCES conversations(id) ON DELETE CASCADE,
            user_id                 INTEGER NOT NULL
                                    REFERENCES users(id) ON DELETE CASCADE,
            summary                 JSONB,
            key_facts               JSONB DEFAULT '[]'::jsonb,
            total_tokens            BIGINT NOT NULL DEFAULT 0,
            last_summary_at_tokens  BIGINT NOT NULL DEFAULT 0,
            summary_version         INTEGER NOT NULL DEFAULT 0,
            l2_pending              BOOLEAN NOT NULL DEFAULT FALSE,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,

        # ── İndeksler ──────────────────────────────────────────────────────
        "CREATE INDEX IF NOT EXISTS idx_chat_room_memory_user_id ON chat_room_memory(user_id);",
        "CREATE INDEX IF NOT EXISTS idx_chat_room_memory_l2_pending ON chat_room_memory(user_id) WHERE l2_pending = TRUE;",

        # ── users tablosuna L2 kolonları ───────────────────────────────────
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS global_memory JSONB;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS l2_updated_at TIMESTAMPTZ;",
    ]

    if op:
        # Alembic modu
        for sql in statements:
            op.execute(sql.strip())
    else:
        # Ham SQL modu — psycopg2 veya psql ile çalıştır
        return statements


def downgrade(op=None):
    statements = [
        "DROP TABLE IF EXISTS chat_room_memory;",
        "ALTER TABLE users DROP COLUMN IF EXISTS global_memory;",
        "ALTER TABLE users DROP COLUMN IF EXISTS l2_updated_at;",
    ]
    if op:
        for sql in statements:
            op.execute(sql.strip())
    else:
        return statements


# ── Alembic env.py'de kullanım ────────────────────────────────────────────────
# from alembic import op as alembic_op
# upgrade(alembic_op)

# ── Doğrudan psql ile çalıştırma ──────────────────────────────────────────────
# psql $DATABASE_URL -c "$(python migrations/add_memory_tables.py)"

if __name__ == "__main__":
    import os
    import psycopg2

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    cursor = conn.cursor()

    print("Migration başlatılıyor: add_memory_tables")
    for sql in upgrade():
        print(f"  Çalıştırılıyor: {sql.strip()[:60]}...")
        cursor.execute(sql)

    print("Migration tamamlandı.")
    cursor.close()
    conn.close()