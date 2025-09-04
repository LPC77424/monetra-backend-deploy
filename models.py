from sqlalchemy import Column, String, Float, Date, Boolean, LargeBinary, Integer, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Transaktion(Base):
    __tablename__ = "transaktionen"

    id = Column(String, primary_key=True)
    typ = Column(String, nullable=False)
    bezeichnung = Column(String, nullable=False)
    betrag = Column(Float, nullable=False)
    datum = Column(Date, nullable=False)
    kategorie = Column(String, nullable=True)
    wiederkehrend = Column(Boolean, default=False)
    beleg_id = Column(String, ForeignKey("belege.beleg_id"), nullable=True)

    beleg = relationship("Beleg", back_populates="transaktionen")

class Beleg(Base):
    __tablename__ = "belege"

    beleg_id = Column(String, primary_key=True)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    data = Column(LargeBinary, nullable=False)

    transaktionen = relationship("Transaktion", back_populates="beleg")
