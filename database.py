from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///monetra.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # nur für SQLite nötig
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

from sqlalchemy.orm import Session
from fastapi import Depends

# Diese Funktion liefert eine DB-Session für FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()