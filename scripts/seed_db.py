import os
import psycopg2
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")

def get_embedding(text):
    """Generate embeddings using a dedicated embedding model via Ollama."""
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/embed",
            json={"model": EMBED_MODEL, "input": text}
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data.get("embedding"), list):
            return data["embedding"]
        embs = data.get("embeddings")
        if isinstance(embs, list) and embs and isinstance(embs[0], list):
            return embs[0]
        print("Unexpected /api/embed response shape: missing embedding(s)")
        return None
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return None

def init_db():
    print(f"Connecting to database at {DB_URL}...")
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        # 1. Run the initial SQL schema
        print("Running init.sql...")
        with open("database/init.sql", "r") as f:
            cur.execute(f.read())
        
        # mig_path = os.path.join(os.path.dirname(__file__), "..", "database", "migrate_v2_doctor_availability.sql")
        # if os.path.isfile(mig_path):
        #     print("Running migrate_v2_doctor_availability.sql ...")
        #     with open(mig_path, "r") as f:
        #         mig_sql = f.read()
        #     for raw in mig_sql.split(";"):
        #         stmt = raw.strip()
        #         if stmt:
        #             cur.execute(stmt)

        conn.commit()
        
        # 2. Update doctor embeddings for semantic search
        #    Build a richer text representation for better similarity matching
        cur.execute("SELECT id, name, specialty FROM doctors")
        doctors = cur.fetchall()
        
        for doc_id, name, specialty in doctors:
            embed_text = f"{name} — {specialty}. Specializes in {specialty.lower()} medicine."
            print(f"  Generating embedding for '{embed_text}'...")
            embedding = get_embedding(embed_text)
            if embedding:
                cur.execute(
                    "UPDATE doctors SET embedding = %s WHERE id = %s",
                    (embedding, doc_id)
                )
            else:
                print(f"  WARNING: Could not generate embedding for doctor {doc_id}")
        
        conn.commit()
        cur.close()
        conn.close()
        print("Database initialized and seeded successfully.")
    except Exception as e:
        print(f"Database initialization failed: {e}")

if __name__ == "__main__":
    init_db()
