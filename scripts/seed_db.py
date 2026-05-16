import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.embedding_util import get_embedding, preload_embedding_model


def _force_reembed() -> bool:
    return os.getenv("FORCE_EMBED_DOCTORS", "").lower() in ("1", "true", "yes")


def _seed_doctor_embeddings(cur) -> None:
    """Compute embeddings only for doctors that do not have one yet."""
    force = _force_reembed()
    if force:
        print("  FORCE_EMBED_DOCTORS=true — regenerating all doctor embeddings…")
        cur.execute("SELECT id, name, specialty FROM doctors")
    else:
        cur.execute(
            "SELECT id, name, specialty FROM doctors WHERE embedding IS NULL"
        )

    doctors = cur.fetchall()
    if not doctors:
        print("  Doctor embeddings already set; skipping (use FORCE_EMBED_DOCTORS=true to redo).")
        return

    for doc_id, name, specialty in doctors:
        embed_text = f"{name} — {specialty}. Specializes in {specialty.lower()} medicine."
        print(f"  Generating embedding for '{embed_text}'...")
        embedding = get_embedding(embed_text)
        if embedding:
            cur.execute(
                "UPDATE doctors SET embedding = %s WHERE id = %s",
                (embedding, doc_id),
            )
        else:
            print(f"  WARNING: Could not generate embedding for doctor {doc_id}")


def init_db():
    print(f"Connecting to database at {DB_URL}...")
    try:
        print("Loading embedding model for seed…")
        preload_embedding_model()
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        print("Running init.sql...")
        with open(_PROJECT_ROOT / "database" / "init.sql", "r") as f:
            cur.execute(f.read())

        conn.commit()

        print("Seeding doctor embeddings (first-time only)…")
        _seed_doctor_embeddings(cur)

        conn.commit()
        cur.close()
        conn.close()
        print("Database initialized and seeded successfully.")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        raise


if __name__ == "__main__":
    init_db()
