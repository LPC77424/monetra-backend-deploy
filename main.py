from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class BetragEingabe(BaseModel):
    betrag: float

class AusgabeEingabe(BaseModel):
    betrag: float
    bezeichnung: str
    kategorie: str

class SparzielEingabe(BaseModel):
    name: str
    betrag: float
    modus: str

class ZahlungEingabe(BaseModel):
    name: str
    betrag: float
    datum: str

kontostand_speicher = 0.0
budget_speicher = 0.0
sparziele_liste = []
ausgaben_liste = []
zahlungen_liste = []

@app.get("/")
def read_root():
    return {"message": "Monetra Backend läuft!"}

@app.get("/kontostand")
def get_kontostand():
    return {"kontostand": kontostand_speicher}

@app.post("/kontostand")
def set_kontostand(eingabe: BetragEingabe):
    global kontostand_speicher
    kontostand_speicher = eingabe.betrag
    return {"kontostand": kontostand_speicher}

@app.post("/kontostand/reset")
def reset_kontostand():
    global kontostand_speicher
    kontostand_speicher = 0.0
    return {"message": "Kontostand zurückgesetzt"}

@app.get("/ausgaben")
def get_ausgaben():
    return {"ausgaben": ausgaben_liste}

@app.post("/ausgabe")
def add_ausgabe(eingabe: AusgabeEingabe):
    ausgaben_liste.append({
        "bezeichnung": eingabe.bezeichnung,
        "betrag": eingabe.betrag,
        "kategorie": eingabe.kategorie
    })
    return {"message": "Ausgabe hinzugefügt"}

@app.post("/ausgaben/reset")
def reset_ausgaben():
    global ausgaben_liste
    ausgaben_liste = []
    return {"message": "Ausgaben zurückgesetzt"}

@app.get("/gesamt_sparziele")
def get_gesamt_sparziele():
    return {"details": sparziele_liste}

@app.post("/sparziel")
def add_sparziel(eingabe: SparzielEingabe):
    sparziele_liste.append({"name": eingabe.name, "betrag": eingabe.betrag, "modus": eingabe.modus})
    return {"message": "Sparziel hinzugefügt"}

@app.post("/sparziele/reset")
def reset_sparziele():
    global sparziele_liste
    sparziele_liste = []
    return {"message": "Sparziele zurückgesetzt"}

@app.get("/verfuegbar")
def get_verfuegbar():
    total_ausgaben = sum(item["betrag"] for item in ausgaben_liste)
    total_sparziele = sum(item["betrag"] for item in sparziele_liste)
    total_zahlungen = sum(item["betrag"] for item in zahlungen_liste)
    return {"verfuegbar": kontostand_speicher - total_ausgaben - total_sparziele - total_zahlungen}

@app.post("/zahlung")
def add_zahlung(eingabe: ZahlungEingabe):
    zahlungen_liste.append({"name": eingabe.name, "betrag": eingabe.betrag, "datum": eingabe.datum})
    return {"message": "Zahlung hinzugefügt"}

@app.get("/zahlungen")
def get_zahlungen():
    return {"zahlungen": zahlungen_liste}

@app.post("/zahlungen/reset")
def reset_zahlungen():
    global zahlungen_liste
    zahlungen_liste = []
    return {"message": "Zahlungen zurückgesetzt"}

@app.post("/budgets/reset")
def reset_budgets():
    global budget_speicher
    budget_speicher = 0.0
    return {"message": "Budgets zurückgesetzt"}

@app.post("/alles/reset")
def reset_alles():
    reset_kontostand()
    reset_ausgaben()
    reset_sparziele()
    reset_budgets()
    reset_zahlungen()
    return {"message": "Alle Daten zurückgesetzt"}
