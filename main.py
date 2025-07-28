from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import uuid4

app = FastAPI()

# Statt "*": nur deine Frontend-Domain(n) hier eintragen!
origins = ["https://startling-souffle-cd2bcd.netlify.app", 
           "http://localhost:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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
    alle_zukuenftig: Optional[bool] = False

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
        original = datetime.strptime(transaktion["datum"], "%Y-%m-%d").date()
        for i in range(1, 12):
            yr = original.year + (original.month + i - 1) // 12
            mo = (original.month + i - 1) % 12 + 1
            nd = original.replace(year=yr, month=mo)
            k = transaktion.copy()
            k["id"] = str(uuid4())
            k["datum"] = nd.isoformat()
            transaktionen_liste.append(k)
    return {"message": "Transaktion gespeichert", "id": transaktion["id"]}

@app.get("/transaktionen")
def get_transaktionen():
    return {"transaktionen": transaktionen_liste}

@app.get("/transaktion/{id}")
def get_transaktion_by_id(id: str):
    t = next((x for x in transaktionen_liste if x["id"] == id), None)
    if not t:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    return t

@app.put("/transaktion/{id}")
def update_transaktion(id: str, eingabe: TransaktionEingabe):
    try:
        gefunden = next((t for t in transaktionen_liste if t["id"] == id), None)
        if not gefunden:
            raise HTTPException(status_code=404, detail="Nicht gefunden")
        datum_alt = datetime.strptime(gefunden["datum"], "%Y-%m-%d").date()
        if eingabe.alle_zukuenftig and gefunden.get("wiederkehrend"):
            # alte Serie entfernen
            transaktionen_liste[:] = [
                t for t in transaktionen_liste
                if not (
                    t.get("wiederkehrend")
                    and t["bezeichnung"] == gefunden["bezeichnung"]
                    and datetime.strptime(t["datum"], "%Y-%m-%d").date() >= datum_alt
                )
            ]
            neu = eingabe.dict()
            neu.pop("alle_zukuenftig", None)
            neu["id"] = str(uuid4())
            transaktionen_liste.append(neu)
            if neu.get("wiederkehrend"):
                original = datetime.strptime(neu["datum"], "%Y-%m-%d").date()
                for i in range(1, 12):
                    yr = original.year + (original.month + i - 1) // 12
                    mo = (original.month + i - 1) % 12 + 1
                    nd = original.replace(year=yr, month=mo)
                    cp = neu.copy()
                    cp["id"] = str(uuid4())
                    cp["datum"] = nd.isoformat()
                    transaktionen_liste.append(cp)
            return {"message": "Serie aktualisiert"}
        else:
            for idx, t in enumerate(transaktionen_liste):
                if t["id"] == id:
                    nd = eingabe.dict()
                    nd.pop("alle_zukuenftig", None)
                    transaktionen_liste[idx] = {**nd, "id": id}
                    return {"message": "Transaktion aktualisiert"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/transaktion/{id}")
def delete_transaktion(id: str, eingabe: TransaktionEingabe):
    try:
        ziel = next((t for t in transaktionen_liste if t["id"] == id), None)
        if not ziel:
            raise HTTPException(status_code=404, detail="Nicht gefunden")
        datum_alt = datetime.strptime(ziel["datum"], "%Y-%m-%d").date()
        if eingabe.alle_zukuenftig and ziel.get("wiederkehrend"):
            transaktionen_liste[:] = [
                t for t in transaktionen_liste
                if not (
                    t.get("wiederkehrend")
                    and t["bezeichnung"] == ziel["bezeichnung"]
                    and datetime.strptime(t["datum"], "%Y-%m-%d").date() >= datum_alt
                )
            ]
            return {"message": "Serie gelöscht"}
        else:
            transaktionen_liste[:] = [t for t in transaktionen_liste if t["id"] != id]
            return {"message": "Transaktion gelöscht"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/verfuegbar")
def get_verfuegbar():
    heute = datetime.today().date()
    v = 0.0
    for t in transaktionen_liste:
        d = datetime.strptime(t["datum"], "%Y-%m-%d").date()
        if d <= heute:
            v += t["betrag"] if t["typ"] == "einnahme" else -t["betrag"]
    return {"verfuegbar": v}

@app.get("/naechste-zahlung")
def get_next_payment():
    heute = datetime.today().date()
    z = [
        (datetime.strptime(t["datum"], "%Y-%m-%d").date(), t["bezeichnung"], t["betrag"])
        for t in transaktionen_liste
        if t["typ"] == "zahlung" and datetime.strptime(t["datum"], "%Y-%m-%d").date() >= heute
    ]
    if not z:
        return {"message": "Keine zukünftigen Zahlungen"}
    z.sort()
    d, name, bet = z[0]
    return {"naechste": {"in_tagen": (d - heute).days, "datum": d.isoformat(), "name": name, "betrag": bet}}

@app.get("/naechste-zahlungen")
def get_all_future_payments():
    heute = datetime.today().date()
    future = []
    gesamt = 0.0
    for t in transaktionen_liste:
        if t["typ"] == "zahlung":
            d = datetime.strptime(t["datum"], "%Y-%m-%d").date()
            if d >= heute:
                tage = (d - heute).days
                future.append({"name": t["bezeichnung"], "datum": d.isoformat(), "in_tagen": tage, "betrag": t["betrag"]})
                gesamt += t["betrag"]
    future.sort(key=lambda x: x["in_tagen"])
    return {"gesamt_betrag": gesamt, "zahlungen": future}

@app.get("/monatsreport")
def monatsreport(monat: str):
    try:
        jahr, mo = map(int, monat.split("-"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Format. Erwartet YYYY-MM.")
    filtr = [
        t for t in transaktionen_liste
        if datetime.strptime(t["datum"], "%Y-%m-%d").year == jahr
        and datetime.strptime(t["datum"], "%Y-%m-%d").month == mo
    ]
    erg = {
        "einnahmen": sum(t["betrag"] for t in filtr if t["typ"] == "einnahme"),
        "ausgaben": sum(t["betrag"] for t in filtr if t["typ"] == "ausgabe"),
        "zahlungen": sum(t["betrag"] for t in filtr if t["typ"] == "zahlung"),
        "sparen": sum(t["betrag"] for t in filtr if t["typ"] == "sparen"),
        "anzahl_transaktionen": len(filtr),
        "kategorien": {}
    }
    for t in filtr:
        k = t.get("kategorie") or "Sonstige"
        erg["kategorien"].setdefault(k, 0)
        erg["kategorien"][k] += t["betrag"]
    return erg

@app.post("/reset")
def reset_all():
    transaktionen_liste.clear()
    return {"message": "Alle Daten zurückgesetzt"}
