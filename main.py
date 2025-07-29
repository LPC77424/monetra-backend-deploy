from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import uuid4

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://startling-souffle-cd2bcd.netlify.app",  # Deployment
        "http://localhost:3000",                         # Lokale Tests
        "http://127.0.0.1:5500",                          # Live Server (VS Code)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TransaktionEingabe(BaseModel):
    typ: str
    bezeichnung: str
    betrag: float
    datum: str
    kategorie: Optional[str] = ""
    wiederkehrend: Optional[bool] = False

transaktionen_liste = []

@app.get("/")
def root():
    return {"message": "Backend läuft"}

@app.post("/transaktion")
def add_transaktion(eingabe: TransaktionEingabe):
    t = eingabe.dict()
    t["id"] = str(uuid4())
    transaktionen_liste.append(t)

    if t.get("wiederkehrend"):
        start = datetime.strptime(t["datum"], "%Y-%m-%d").date()
        for i in range(1, 12):
            jahr = start.year + (start.month + i - 1) // 12
            monat = (start.month + i - 1) % 12 + 1
            datum = start.replace(year=jahr, month=monat)
            kopie = t.copy()
            kopie["id"] = str(uuid4())
            kopie["datum"] = datum.isoformat()
            transaktionen_liste.append(kopie)

    return {"message": "Transaktion gespeichert", "id": t["id"]}

@app.get("/transaktionen")
def get_transaktionen():
    return {"transaktionen": transaktionen_liste}

@app.get("/transaktion/{id}")
def get_transaktion_by_id(id: str):
    for t in transaktionen_liste:
        if t["id"] == id:
            return t
    return {"error": "Nicht gefunden"}

@app.put("/transaktion/{id}")
def update_transaktion(id: str, eingabe: TransaktionEingabe, alle_zukuenftig: bool = Query(False)):
    gefunden = next((t for t in transaktionen_liste if t["id"] == id), None)
    if not gefunden:
        return {"error": "Nicht gefunden"}

    datum_alt = datetime.strptime(gefunden["datum"], "%Y-%m-%d").date()

    if alle_zukuenftig and gefunden.get("wiederkehrend"):
        transaktionen_liste[:] = [
            t for t in transaktionen_liste
            if not (
                t.get("wiederkehrend") and
                t["bezeichnung"] == gefunden["bezeichnung"] and
                datetime.strptime(t["datum"], "%Y-%m-%d").date() >= datum_alt
            )
        ]
        neue = eingabe.dict()
        neue["id"] = str(uuid4())
        transaktionen_liste.append(neue)

        if neue.get("wiederkehrend"):
            start = datetime.strptime(neue["datum"], "%Y-%m-%d").date()
            for i in range(1, 12):
                jahr = start.year + (start.month + i - 1) // 12
                monat = (start.month + i - 1) % 12 + 1
                datum = start.replace(year=jahr, month=monat)
                kopie = neue.copy()
                kopie["id"] = str(uuid4())
                kopie["datum"] = datum.isoformat()
                transaktionen_liste.append(kopie)
        return {"message": "Serie aktualisiert"}
    else:
        for idx, t in enumerate(transaktionen_liste):
            if t["id"] == id:
                neue = eingabe.dict()
                transaktionen_liste[idx] = {**neue, "id": id}
                return {"message": "Transaktion aktualisiert"}

@app.delete("/transaktion/{id}")
def delete_transaktion(id: str, alle_zukuenftig: bool = Query(False)):
    ziel = next((t for t in transaktionen_liste if t["id"] == id), None)
    if not ziel:
        return {"error": "Nicht gefunden"}

    datum = datetime.strptime(ziel["datum"], "%Y-%m-%d").date()

    if alle_zukuenftig and ziel.get("wiederkehrend"):
        transaktionen_liste[:] = [
            t for t in transaktionen_liste
            if not (
                t.get("wiederkehrend") and
                t["bezeichnung"] == ziel["bezeichnung"] and
                datetime.strptime(t["datum"], "%Y-%m-%d").date() >= datum
            )
        ]
        return {"message": "Serie gelöscht"}
    else:
        transaktionen_liste[:] = [t for t in transaktionen_liste if t["id"] != id]
        return {"message": "Transaktion gelöscht"}

@app.get("/verfuegbar")
def get_verfuegbar():
    heute = datetime.today().date()
    saldo = 0.0
    for t in transaktionen_liste:
        datum = datetime.strptime(t["datum"], "%Y-%m-%d").date()
        if datum <= heute:
            saldo += t["betrag"] if t["typ"] == "einnahme" else -t["betrag"]
    return {"verfuegbar": saldo}

@app.get("/naechste-zahlungen")
def get_naechste_zahlungen():
    heute = datetime.today().date()
    kommende = [
        {
            "name": t["bezeichnung"],
            "datum": t["datum"],
            "in_tagen": (datetime.strptime(t["datum"], "%Y-%m-%d").date() - heute).days,
            "betrag": t["betrag"]
        }
        for t in transaktionen_liste
        if t["typ"] == "zahlung" and datetime.strptime(t["datum"], "%Y-%m-%d").date() >= heute
    ]
    gesamt = sum(t["betrag"] for t in kommende)
    return {
        "gesamt_betrag": gesamt,
        "zahlungen": sorted(kommende, key=lambda x: x["in_tagen"])
    }

@app.get("/monatsreport")
def monatsreport(monat: str):
    try:
        jahr, monat_zahl = map(int, monat.split("-"))
    except ValueError:
        return {"error": "Ungültiges Format (YYYY-MM)"}

    gefiltert = [
        t for t in transaktionen_liste
        if datetime.strptime(t["datum"], "%Y-%m-%d").year == jahr and
           datetime.strptime(t["datum"], "%Y-%m-%d").month == monat_zahl
    ]
    kategorien = {}
    for t in gefiltert:
        kat = t.get("kategorie", "Sonstige") or "Sonstige"
        kategorien[kat] = kategorien.get(kat, 0) + t["betrag"]

    return {
        "einnahmen": sum(t["betrag"] for t in gefiltert if t["typ"] == "einnahme"),
        "ausgaben": sum(t["betrag"] for t in gefiltert if t["typ"] == "ausgabe"),
        "zahlungen": sum(t["betrag"] for t in gefiltert if t["typ"] == "zahlung"),
        "sparen": sum(t["betrag"] for t in gefiltert if t["typ"] == "sparen"),
        "anzahl_transaktionen": len(gefiltert),
        "kategorien": kategorien
    }

@app.post("/reset")
def reset_all():
    global transaktionen_liste
    transaktionen_liste = []
    return {"message": "Alle Daten wurden zurückgesetzt"}
