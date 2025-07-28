from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import uuid4

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
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

@app.post("/transaktion")
def add_transaktion(eingabe: TransaktionEingabe):
    trans = eingabe.dict()
    trans["id"] = str(uuid4())
    transaktionen_liste.append(trans)
    if trans.get("wiederkehrend"):
        orig = datetime.strptime(trans["datum"], "%Y-%m-%d").date()
        for m in range(1, 12):
            year = orig.year + (orig.month + m - 1) // 12
            month = (orig.month + m - 1) % 12 + 1
            new = orig.replace(year=year, month=month)
            k = trans.copy(); k["id"] = str(uuid4()); k["datum"] = new.isoformat()
            transaktionen_liste.append(k)
    return {"message": "Transaktion gespeichert", "id": trans["id"]}

@app.get("/transaktionen")
def get_transaktionen():
    return {"transaktionen": transaktionen_liste}

@app.get("/transaktion/{id}")
def get_transaktion_by_id(id: str):
    t = next((x for x in transaktionen_liste if x["id"] == id), None)
    return t or {"error": "Nicht gefunden"}

@app.put("/transaktion/{id}")
def update_transaktion(id: str, eingabe: TransaktionEingabe, alle_zukuenftig: bool = Query(False)):
    orig = next((x for x in transaktionen_liste if x["id"] == id), None)
    if not orig: return {"error": "Nicht gefunden"}
    orig_date = datetime.strptime(orig["datum"], "%Y-%m-%d").date()
    if alle_zukuenftig and orig.get("wiederkehrend"):
        transaktionen_liste[:] = [
            t for t in transaktionen_liste
            if not (t.get("wiederkehrend") and t["bezeichnung"] == orig["bezeichnung"] and
                    datetime.strptime(t["datum"], "%Y-%m-%d").date() >= orig_date)
        ]
        neu = eingabe.dict(); neu.pop("alle_zukuenftig", None)
        neu["id"] = str(uuid4()); transaktionen_liste.append(neu)
        if neu.get("wiederkehrend"):
            base = datetime.strptime(neu["datum"], "%Y-%m-%d").date()
            for m in range(1, 12):
                y = base.year + (base.month + m - 1) // 12
                mo = (base.month + m - 1) % 12 + 1
                nd = base.replace(year=y, month=mo)
                kp = neu.copy(); kp["id"] = str(uuid4()); kp["datum"] = nd.isoformat()
                transaktionen_liste.append(kp)
        return {"message": "Serie aktualisiert"}
    else:
        idx = transaktionen_liste.index(orig)
        daten = eingabe.dict(); daten.pop("alle_zukuenftig", None)
        transaktionen_liste[idx] = {**daten, "id": id}
        return {"message": "Transaktion aktualisiert"}

@app.delete("/transaktion/{id}")
def delete_transaktion(id: str, alle_zukuenftig: bool = Query(False)):
    ziel = next((x for x in transaktionen_liste if x["id"] == id), None)
    if not ziel: return {"error": "Nicht gefunden"}
    date_z = datetime.strptime(ziel["datum"], "%Y-%m-%d").date()
    if alle_zukuenftig and ziel.get("wiederkehrend"):
        transaktionen_liste[:] = [
            t for t in transaktionen_liste
            if not (t.get("wiederkehrend") and t["bezeichnung"] == ziel["bezeichnung"] and
                    datetime.strptime(t["datum"], "%Y-%m-%d").date() >= date_z)
        ]
        return {"message": "Serie gelöscht"}
    transaktionen_liste[:] = [t for t in transaktionen_liste if t["id"] != id]
    return {"message": "Transaktion gelöscht"}

@app.get("/verfuegbar")
def get_verfuegbar():
    today = datetime.today().date()
    summe = 0.0
    for t in transaktionen_liste:
        d = datetime.strptime(t["datum"], "%Y-%m-%d").date()
        if d <= today:
            summe += t["betrag"] if t["typ"] == "einnahme" else -t["betrag"]
    return {"verfuegbar": summe}

@app.get("/naechste-zahlung")
def get_next_payment():
    today = datetime.today().date()
    future = [(datetime.strptime(t["datum"], "%Y-%m-%d").date(), t["bezeichnung"], t["betrag"])
              for t in transaktionen_liste if t["typ"] == "zahlung" and
              datetime.strptime(t["datum"], "%Y-%m-%d").date() >= today]
    if not future: return {"message": "Keine zukünftigen Zahlungen"}
    future.sort()
    d, b, amount = future[0]
    return {"naechste": {"in_tagen": (d - today).days, "datum": d.isoformat(), "name": b, "betrag": amount}}

@app.get("/naechste-zahlungen")
def get_all_future_payments():
    today = datetime.today().date()
    zahlen = []
    total = 0.0
    for t in transaktionen_liste:
        if t["typ"] == "zahlung":
            d = datetime.strptime(t["datum"], "%Y-%m-%d").date()
            if d >= today:
                zahlen.append({"name": t["bezeichnung"], "datum": d.isoformat(),
                               "in_tagen": (d - today).days, "betrag": t["betrag"]})
                total += t["betrag"]
    return {"gesamt_betrag": total, "zahlungen": sorted(zahlen, key=lambda x: x["in_tagen"])}

@app.get("/monatsreport")
def monatsreport(monat: str):
    try:
        Y, M = map(int, monat.split("-"))
    except:
        return {"error": "Ungültiges Format (YYYY-MM)"}
    gef = [t for t in transaktionen_liste if
           datetime.strptime(t["datum"], "%Y-%m-%d").year == Y and
           datetime.strptime(t["datum"], "%Y-%m-%d").month == M]
    res = {
        "einnahmen": sum(t["betrag"] for t in gef if t["typ"] == "einnahme"),
        "ausgaben": sum(t["betrag"] for t in gef if t["typ"] == "ausgabe"),
        "zahlungen": sum(t["betrag"] for t in gef if t["typ"] == "zahlung"),
        "sparen": sum(t["betrag"] for t in gef if t["typ"] == "sparen"),
        "anzahl_transaktionen": len(gef),
        "kategorien": {}
    }
    for t in gef:
        k = t.get("kategorie") or "Sonstige"
        res["kategorien"].setdefault(k, 0)
        res["kategorien"][k] += t["betrag"]
    return res

@app.post("/reset")
def reset_all():
    global transaktionen_liste
    transaktionen_liste = []
    return {"message": "Alle Daten wurden zurückgesetzt"}
