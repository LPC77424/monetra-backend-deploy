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

@app.post("/transaktion")
def add_transaktion(eingabe: TransaktionEingabe):
    transaktion = eingabe.dict()
    transaktion["id"] = str(uuid4())
    transaktionen_liste.append(transaktion)
    if transaktion.get("wiederkehrend"):
        original = datetime.strptime(transaktion["datum"], "%Y-%m-%d").date()
        for mon in range(1, 12):
            j = original.year + (original.month + mon - 1) // 12
            m = (original.month + mon - 1) % 12 + 1
            nd = original.replace(year=j, month=m)
            kopie = transaktion.copy(); kopie["id"] = str(uuid4()); kopie["datum"] = nd.isoformat()
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
def update_transaktion(
    id: str,
    eingabe: TransaktionEingabe,
    alle_zukuenftig: bool = Query(False),
):
    t_old = next((t for t in transaktionen_liste if t["id"] == id), None)
    if not t_old:
        return {"error": "Nicht gefunden"}
    d_old = datetime.strptime(t_old["datum"], "%Y-%m-%d").date()
    if alle_zukuenftig and t_old.get("wiederkehrend"):
        transaktionen_liste[:] = [
            t for t in transaktionen_liste
            if not (
                t.get("wiederkehrend")
                and t["bezeichnung"] == t_old["bezeichnung"]
                and datetime.strptime(t["datum"], "%Y-%m-%d").date() >= d_old
            )
        ]
        neu = eingabe.dict(); neu["id"] = str(uuid4())
        transaktionen_liste.append(neu)
        if neu.get("wiederkehrend"):
            orig = datetime.strptime(neu["datum"], "%Y-%m-%d").date()
            for mon in range(1, 12):
                j = orig.year + (orig.month + mon - 1) // 12
                m = (orig.month + mon - 1) % 12 + 1
                nd = orig.replace(year=j, month=m)
                k = neu.copy(); k["id"] = str(uuid4()); k["datum"] = nd.isoformat()
                transaktionen_liste.append(k)
        return {"message": "Serie aktualisiert"}
    for i, t in enumerate(transaktionen_liste):
        if t["id"] == id:
            d = eingabe.dict(); transaktionen_liste[i] = {**d, "id": id}
            return {"message": "Transaktion aktualisiert"}

@app.delete("/transaktion/{id}")
def delete_transaktion(id: str, alle_zukuenftig: bool = Query(False)):
    t_old = next((t for t in transaktionen_liste if t["id"] == id), None)
    if not t_old:
        return {"error": "Nicht gefunden"}
    d_old = datetime.strptime(t_old["datum"], "%Y-%m-%d").date()
    if alle_zukuenftig and t_old.get("wiederkehrend"):
        transaktionen_liste[:] = [
            t for t in transaktionen_liste
            if not (
                t.get("wiederkehrend")
                and t["bezeichnung"] == t_old["bezeichnung"]
                and datetime.strptime(t["datum"], "%Y-%m-%d").date() >= d_old
            )
        ]
        return {"message": "Serie gelöscht"}
    transaktionen_liste[:] = [t for t in transaktionen_liste if t["id"] != id]
    return {"message": "Transaktion gelöscht"}

@app.get("/verfuegbar")
def get_verfuegbar():
    heute = datetime.today().date(); g = 0.0
    for t in transaktionen_liste:
        d = datetime.strptime(t["datum"], "%Y-%m-%d").date()
        g += t["betrag"] if t["typ"] == "einnahme" and d <= heute else 0
        g -= t["betrag"] if t["typ"] != "einnahme" and d <= heute else 0
    return {"verfuegbar": g}
