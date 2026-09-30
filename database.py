"""
Database engine + session setup.

Defaults to a local SQLite file (setu.db) so the whole backend runs with zero
external setup. For a real deployment, set the DATABASE_URL environment
variable to a Cloud SQL / Postgres connection string, e.g.:

    DATABASE_URL=postgresql+psycopg2://user:password@/setu?host=/cloudsql/PROJECT:REGION:INSTANCE

No other code needs to change — SQLAlchemy handles the rest.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./setu.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
# pool_pre_ping: check a connection is still alive before using it. Cheap,
# and it matters here — free-tier cloud Postgres (Aiven, Cloud SQL) can drop
# idle connections, which would otherwise surface as a confusing 500 error
# on whichever request happens to be unlucky enough to get the dead one.
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
