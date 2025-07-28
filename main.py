from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import uuid4

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
def read_root():
    return {"message": "Monetra Backend läuft!"}

@app.post("/transaktion")
def add_transaktion(eingabe: TransaktionEingabe):
    transaktion = eingabe.dict()
    transaktion["id"] = str(uuid4())
    transaktionen_liste.append(transaktion)

    if transaktion.get("wiederkehrend"):
        original_datum = datetime.strptime(transaktion["datum"], "%Y-%m-%d").date()
        for monat in range(1, 12):
            jahr = original_datum.year + (original_datum.month + monat - 1) // 12
            monat_neu = (original_datum.month + monat - 1) % 12 + 1
            neues_datum = original_datum.replace(year=jahr, month=monat_neu)
            kopie = transaktion.copy()
            kopie["id"] = str(uuid4())
            kopie["datum"] = neues_datum.isoformat()
            transaktionen_liste.append(kopie)

    return {"message": "Transaktion gespeichert", "id": transaktion["id"]}

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
        neue_transaktion = eingabe.dict()
        neue_transaktion["id"] = str(uuid4())
        transaktionen_liste.append(neue_transaktion)

        if neue_transaktion.get("wiederkehrend"):
            original_datum = datetime.strptime(neue_transaktion["datum"], "%Y-%m-%d").date()
            for monat in range(1, 12):
                jahr = original_datum.year + (original_datum.month + monat - 1) // 12
                monat_neu = (original_datum.month + monat - 1) % 12 + 1
                neues_datum = original_datum.replace(year=jahr, month=monat_neu)
                kopie = neue_transaktion.copy()
                kopie["id"] = str(uuid4())
                kopie["datum"] = neues_datum.isoformat()
                transaktionen_liste.append(kopie)
        return {"message": "Serie aktualisiert"}
    else:
        for idx, t in enumerate(transaktionen_liste):
            if t["id"] == id:
                neue_daten = eingabe.dict()
                transaktionen_liste[idx] = {**neue_daten, "id": id}
                return {"message": "Transaktion aktualisiert"}

@app.delete("/transaktion/{id}")
def delete_transaktion(id: str, alle_zukuenftig: bool = Query(False)):
    ziel = next((t for t in transaktionen_liste if t["id"] == id), None)
    if not ziel:
        return {"error": "Nicht gefunden"}

    datum_ziel = datetime.strptime(ziel["datum"], "%Y-%m-%d").date()

    if alle_zukuenftig and ziel.get("wiederkehrend"):
        transaktionen_liste[:] = [
            t for t in transaktionen_liste
            if not (
                t.get("wiederkehrend") and
                t["bezeichnung"] == ziel["bezeichnung"] and
                datetime.strptime(t["datum"], "%Y-%m-%d").date() >= datum_ziel
            )
        ]
        return {"message": "Serie gelöscht"}
    else:
        transaktionen_liste[:] = [t for t in transaktionen_liste if t["id"] != id]
        return {"message": "Transaktion gelöscht"}

@app.get("/verfuegbar")
def get_verfuegbar():
    heute = datetime.today().date()
    verfuegbar = 0.0
    for t in transaktionen_liste:
        datum = datetime.strptime(t["datum"], "%Y-%m-%d").date()
        if datum <= heute:
            if t["typ"] == "einnahme":
                verfuegbar += t["betrag"]
            else:
                verfuegbar -= t["betrag"]
    return {"verfuegbar": verfuegbar}

@app.get("/naechste-zahlung")
def get_next_payment():
    heute = datetime.today().date()
    zukunft = [
        (
            datetime.strptime(t["datum"], "%Y-%m-%d").date(),
            t["bezeichnung"],
            t["betrag"]
        )
        for t in transaktionen_liste
        if t["typ"] == "zahlung" and datetime.strptime(t["datum"], "%Y-%m-%d").date() >= heute
    ]

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

@app.get("/naechste-zahlungen")
def get_all_future_payments():
    heute = datetime.today().date()
    future = []
    gesamt_betrag = 0.0

    for t in transaktionen_liste:
        if t["typ"] == "zahlung":
            zahl_datum = datetime.strptime(t["datum"], "%Y-%m-%d").date()
            if zahl_datum >= heute:
                tage = (zahl_datum - heute).days
                future.append({
                    "name": t["bezeichnung"],
                    "datum": zahl_datum.isoformat(),
                    "in_tagen": tage,
                    "betrag": t["betrag"]
                })
                gesamt_betrag += t["betrag"]

    return {
        "gesamt_betrag": gesamt_betrag,
        "zahlungen": sorted(future, key=lambda z: z["in_tagen"])
    }

@app.get("/monatsreport")
def monatsreport(monat: str):
    try:
        jahr, monat_zahl = map(int, monat.split("-"))
    except ValueError:
        return {"error": "Ungültiges Format (Erwartet YYYY-MM)"}

    gefiltert = [
        t for t in transaktionen_liste
        if datetime.strptime(t["datum"], "%Y-%m-%d").year == jahr and
           datetime.strptime(t["datum"], "%Y-%m-%d").month == monat_zahl
    ]

    result = {
        "einnahmen": sum(t["betrag"] for t in gefiltert if t["typ"] == "einnahme"),
        "ausgaben": sum(t["betrag"] for t in gefiltert if t["typ"] == "ausgabe"),
        "zahlungen": sum(t["betrag"] for t in gefiltert if t["typ"] == "zahlung"),
        "sparen": sum(t["betrag"] for t in gefiltert if t["typ"] == "sparen"),
        "anzahl_transaktionen": len(gefiltert),
        "kategorien": {}
    }

    for t in gefiltert:
        kat = t.get("kategorie", "Sonstige") or "Sonstige"
        result["kategorien"].setdefault(kat, 0)
        result["kategorien"][kat] += t["betrag"]

    return result

@app.post("/reset")
def reset_all():
    global transaktionen_liste
    transaktionen_liste = []
    return {"message": "Alle Daten wurden zurückgesetzt"}
