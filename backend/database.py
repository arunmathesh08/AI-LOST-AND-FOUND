import os
import re
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Load .env if present
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

if os.path.exists(ENV_PATH):
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k and v and k not in os.environ:
                        os.environ[k] = v
    except Exception as e:
        print("Database config notice:", e)

# Resolve Database URL (Supabase PostgreSQL / SQLite fallback)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(BASE_DIR, 'lost_and_found.db')}"
).strip()


def resolve_database_url(raw_url: str) -> str:
    """Normalize and format the database URL for SQLAlchemy & PostgreSQL drivers."""
    if not raw_url:
        return f"sqlite:///{os.path.join(BASE_DIR, 'lost_and_found.db')}"
    
    url = raw_url.strip()
    
    # Unwrap bracketed password notation if present, e.g. :[password]@ -> :password@
    url = re.sub(r':\[(.*?)\]@', r':\1@', url)
    
    # Handle postgres scheme compatibility
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    
    # Supabase connection resilience: Test port 6543 vs 5432
    if "supabase.com:6543" in url:
        try:
            import psycopg
            # Quick 2-second probe for pooler port 6543
            with psycopg.connect(url, connect_timeout=2) as conn:
                pass
        except Exception:
            # Fallback to port 5432 (Session mode / direct connection) if pooler port 6543 is unavailable
            url = url.replace(":6543", ":5432")

    return url


RESOLVED_DB_URL = resolve_database_url(DATABASE_URL)

if RESOLVED_DB_URL.startswith("sqlite"):
    engine = create_engine(
        RESOLVED_DB_URL,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(
        RESOLVED_DB_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=10,
        max_overflow=20
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
