from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
from sqlalchemy.orm import Session


# .env laden
load_dotenv()

# Verbindung zur PostgreSQL-Datenbank aus der .env-Datei
DATABASE_URL = os.getenv("DATABASE_URL")

# Engine erstellen
engine = create_engine(DATABASE_URL)

# Session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Basis-Klasse für Modelle
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close ()    