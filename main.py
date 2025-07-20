from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🎯 NEUES MODELL: Einheitliche Transaktion
class TransaktionEingabe(BaseModel):
    typ: str  # "einnahme", "ausgabe", "zahlung", "sparen"
    bezeichnung: str
    betrag: float
    datum: str  # Format: "YYYY-MM-DD"
    kategorie: Optional[str] = ""

# 🧠 SPEICHER
kontostand_speicher = 0.0
transaktionen_liste = []

# ✅ START-SEITE
@app.get("/")
def read_root():
    return {"message": "Monetra Backend läuft!"}

# 💾 TRANSKATION SPEICHERN
@app.post("/transaktion")
def add_transaktion(eingabe: TransaktionEingabe):
    global kontostand_speicher
    transaktionen_liste.append(eingabe.dict())

    if eingabe.typ == "einnahme":
        kontostand_speicher += eingabe.betrag
    else:
        kontostand_speicher -= eingabe.betrag

    return {
        "message": "Transaktion gespeichert",
        "neuer_kontostand": kontostand_speicher
    }

# 📜 ALLE TRANSAKTIONEN LADEN
@app.get("/transaktionen")
def get_transaktionen():
    return {"transaktionen": transaktionen_liste}

# 💰 VERFÜGBARER BETRAG
@app.get("/verfuegbar")
def get_verfuegbar():
    return {"verfuegbar": kontostand_speicher}

# 📅 NÄCHSTE ZAHLUNG ANZEIGEN
@app.get("/naechste-zahlung")
def get_next_payment():
    heute = datetime.today().date()
    zukunft = []

    for t in transaktionen_liste:
        if t["typ"] == "zahlung":
            zahl_datum = datetime.strptime(t["datum"], "%Y-%m-%d").date()
            if zahl_datum >= heute:
                zukunft.append((zahl_datum, t["bezeichnung"], t["betrag"]))

    if not zukunft:
        return {"message": "Keine zukünftigen Zahlungen"}
    
    zukunft.sort()
    naechste = zukunft[0]
    tage = (naechste[0] - heute).days
    return {
        "naechste": {
            "in_tagen": tage,
            "datum": naechste[0].isoformat(),
            "name": naechste[1],
            "betrag": naechste[2]
        }
    }

# 🔁 RESET
@app.post("/reset")
def reset_all():
    global kontostand_speicher, transaktionen_liste
    kontostand_speicher = 0.0
    transaktionen_liste = []
    return {"message": "Alle Daten wurden zurückgesetzt"}

