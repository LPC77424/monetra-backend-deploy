from sqlalchemy import Column, String, Float, Date, Boolean, LargeBinary, Integer, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

Base = declarative_base()

class Transaktion(Base):
    __tablename__ = "transaktionen"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    typ = Column(String, nullable=False)
    bezeichnung = Column(String, nullable=False)
    betrag = Column(Float, nullable=False)
    datum = Column(Date, nullable=False)
    kategorie = Column(String, nullable=True)
    wiederkehrend = Column(Boolean, default=False)
    beleg_id = Column(String, ForeignKey("belege.beleg_id"), nullable=True)
    waehrung = Column(String, default="CHF")
    serie = Column(String, nullable=True)

    beleg = relationship("Beleg", back_populates="transaktionen")

class Beleg(Base):
    __tablename__ = "belege"

    beleg_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    data = Column(LargeBinary, nullable=False)

    transaktionen = relationship("Transaktion", back_populates="beleg")

from pydantic import BaseModel
from typing import Optional
from datetime import date

class TransaktionEingabe(BaseModel):
    typ: str
    bezeichnung: str
    betrag: float
    datum: date
    kategorie: Optional[str] = None
    wiederkehrend: Optional[bool] = False

    # NEU:
    beleg_id: Optional[str] = None
 