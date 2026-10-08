import os
import re
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

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

# Default Supabase PostgreSQL connection
DEFAULT_SUPABASE_URL = "postgresql://postgres.ucstlplkimcmdcxeghrp:arun6844684@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres"

# Resolve Database URL (Supabase PostgreSQL / SQLite fallback)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    DEFAULT_SUPABASE_URL
).strip()


def resolve_database_url(raw_url: str) -> str:
    """Normalize and format the database URL for SQLAlchemy & PostgreSQL drivers."""
    if not raw_url:
        raw_url = DEFAULT_SUPABASE_URL
    
    url = raw_url.strip()
    
    # Unwrap bracketed password notation if present, e.g. :[password]@ -> :password@
    url = re.sub(r':\[(.*?)\]@', r':\1@', url)
    
    # Handle postgres scheme compatibility
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    
    # Supabase connection resilience: Port 5432 is the universal session pooler port
    if "supabase.com:6543" in url:
        url = url.replace(":6543", ":5432")

    # Handle serverless read-only filesystem for SQLite if ever selected
    if url.startswith("sqlite"):
        if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
            url = "sqlite:////tmp/lost_and_found.db"

    return url


RESOLVED_DB_URL = resolve_database_url(DATABASE_URL)

is_serverless = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

if RESOLVED_DB_URL.startswith("sqlite"):
    engine = create_engine(
        RESOLVED_DB_URL,
        connect_args={"check_same_thread": False}
    )
elif is_serverless:
    # NullPool prevents connection exhaustion on Vercel serverless functions
    engine = create_engine(
        RESOLVED_DB_URL,
        poolclass=NullPool,
        pool_pre_ping=True
    )
else:
    engine = create_engine(
        RESOLVED_DB_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
