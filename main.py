from fastapi import FastAPI, Query, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import uuid4
from io import BytesIO

app = FastAPI()

# Passen: deine Frontend-Domains hier eintragen
ALLOWED_ORIGINS = [
    "https://startling-souffle-cd2bcd.netlify.app",  # Netlify
    "http://127.0.0.1:5500",                          # Live Server
    "http://localhost:5500",                          # Variante
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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
    beleg_id: Optional[str] = None  # NEU: Beleg-Verknüpfung

# In-Memory-Speicher (dev)
transaktionen_liste: List[Dict[str, Any]] = []
belege_store: Dict[str, Dict[str, Any]] = {}  # id -> {filename, content_type, data(bytes), size}

# Hilfsfunktion: sichere Monats-Inkremente (28/29/30/31 Handling)
def add_months_safe(date_obj: datetime.date, months: int):
    y = date_obj.year + (date_obj.month - 1 + months) // 12
    m = (date_obj.month - 1 + months) % 12 + 1
    d = min(date_obj.day, [31,29 if y%4==0 and (y%100!=0 or y%400==0) else 28,31,30,31,30,31,31,30,31,30,31][m-1])
    return date_obj.replace(year=y, month=m, day=d)

@app.get("/")
def read_root():
    return {"message": "Monetra Backend läuft!"}

# ---------- Belege ----------
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB

@app.post("/upload")
async def upload_beleg(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Datei zu groß (max. 5MB)")
    beleg_id = str(uuid4())
    belege_store[beleg_id] = {
        "filename": file.filename,
        "content_type": file.content_type or "application/octet-stream",
        "data": data,
        "size": len(data),
    }
    return {"beleg_id": beleg_id, "filename": file.filename, "size": len(data)}

@app.get("/beleg/{beleg_id}")
def get_beleg(beleg_id: str):
    doc = belege_store.get(beleg_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Beleg nicht gefunden")
    return StreamingResponse(
        BytesIO(doc["data"]),
        media_type=doc["content_type"],
        headers={"Content-Disposition": f'inline; filename="{doc["filename"]}"'}
    )

@app.delete("/beleg/{beleg_id}")
def delete_beleg(beleg_id: str):
    if beleg_id not in belege_store:
        raise HTTPException(status_code=404, detail="Beleg nicht gefunden")
    # Beleg aus Transaktionen lösen
    for t in transaktionen_liste:
        if t.get("beleg_id") == beleg_id:
            t["beleg_id"] = None
    del belege_store[beleg_id]
    return {"message": "Beleg gelöscht"}

# ---------- Transaktionen ----------
@app.post("/transaktion")
def add_transaktion(eingabe: TransaktionEingabe):
    transaktion = eingabe.dict()
    transaktion["id"] = str(uuid4())
    transaktionen_liste.append(transaktion)

    # Wiederkehrend: weitere 11 Monate erzeugen
    if transaktion.get("wiederkehrend"):
        start = datetime.strptime(transaktion["datum"], "%Y-%m-%d").date()
        for i in range(1, 12):
            neues_datum = add_months_safe(start, i)
            kopie = transaktion.copy()
            kopie["id"] = str(uuid4())
            kopie["datum"] = neues_datum.isoformat()
            transaktionen_liste.append(kopie)

    return {"message": "Transaktion gespeichert", "id": transaktion["id"]}

@app.get("/transaktionen")
def get_transaktionen(monat: Optional[str] = None, nur_serie: bool = False):
    """
    - ohne Parameter: alle (wie bisher)
    - ?monat=YYYY-MM : nur dieser Monat
    - ?nur_serie=true : (optional) nur wiederkehrende anzeigen
    """
    if not monat and not nur_serie:
        return {"transaktionen": transaktionen_liste}

    result = transaktionen_liste
    if monat:
        try:
            y, m = map(int, monat.split("-"))
        except Exception:
            raise HTTPException(status_code=422, detail="Ungültiger Monat (YYYY-MM)")
        result = [
            t for t in result
            if datetime.strptime(t["datum"], "%Y-%m-%d").year == y and
               datetime.strptime(t["datum"], "%Y-%m-%d").month == m
        ]
    if nur_serie:
        result = [t for t in result if t.get("wiederkehrend")]

    return {"transaktionen": result}

@app.get("/transaktion/{id}")
def get_transaktion_by_id(id: str):
    for t in transaktionen_liste:
        if t["id"] == id:
            return t
    raise HTTPException(status_code=404, detail="Nicht gefunden")

@app.put("/transaktion/{id}")
def update_transaktion(id: str, eingabe: TransaktionEingabe, alle_zukuenftig: bool = Query(False)):
    gefunden = next((t for t in transaktionen_liste if t["id"] == id), None)
    if not gefunden:
        raise HTTPException(status_code=404, detail="Nicht gefunden")

    datum_alt = datetime.strptime(gefunden["datum"], "%Y-%m-%d").date()

    if alle_zukuenftig and gefunden.get("wiederkehrend"):
        # Serie ab diesem Datum löschen
        transaktionen_liste[:] = [
            t for t in transaktionen_liste
            if not (
                t.get("wiederkehrend")
                and t["bezeichnung"] == gefunden["bezeichnung"]
                and datetime.strptime(t["datum"], "%Y-%m-%d").date() >= datum_alt
            )
        ]
        # Neue Serie anlegen mit neuen Werten
        neu = eingabe.dict()
        neu["id"] = str(uuid4())
        transaktionen_liste.append(neu)
        if neu.get("wiederkehrend"):
            start = datetime.strptime(neu["datum"], "%Y-%m-%d").date()
            for i in range(1, 12):
                nd = add_months_safe(start, i)
                kopie = neu.copy()
                kopie["id"] = str(uuid4())
                kopie["datum"] = nd.isoformat()
                transaktionen_liste.append(kopie)
        return {"message": "Serie aktualisiert"}
    else:
        for idx, t in enumerate(transaktionen_liste):
            if t["id"] == id:
                neu = eingabe.dict()
                transaktionen_liste[idx] = {**neu, "id": id}
                return {"message": "Transaktion aktualisiert"}

@app.delete("/transaktion/{id}")
def delete_transaktion(id: str, alle_zukuenftig: bool = Query(False)):
    ziel = next((t for t in transaktionen_liste if t["id"] == id), None)
    if not ziel:
        raise HTTPException(status_code=404, detail="Nicht gefunden")

    datum_ziel = datetime.strptime(ziel["datum"], "%Y-%m-%d").date()

    if alle_zukuenftig and ziel.get("wiederkehrend"):
        transaktionen_liste[:] = [
            t for t in transaktionen_liste
            if not (
                t.get("wiederkehrend")
                and t["bezeichnung"] == ziel["bezeichnung"]
                and datetime.strptime(t["datum"], "%Y-%m-%d").date() >= datum_ziel
            )
        ]
        return {"message": "Serie gelöscht"}
    else:
        transaktionen_liste[:] = [t for t in transaktionen_liste if t["id"] != id]
        return {"message": "Transaktion gelöscht"}

# ---------- Dashboard ----------
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
        raise HTTPException(status_code=422, detail="Ungültiges Format (YYYY-MM)")
    gefiltert = [
        t for t in transaktionen_liste
        if datetime.strptime(t["datum"], "%Y-%m-%d").year == jahr and
           datetime.strptime(t["datum"], "%Y-%m-%d").month == monat_zahl
    ]
    result = {
        "einnahmen": sum(t["betrag"] for t in gefiltert if t["typ"] == "einnahme"),
        "ausgaben": sum(t["betrag"] for t in gefiltert if t["typ"] == "ausgabe"),
        "zahlungen": sum(t["betrag"] for t in gefiltert if t["typ"] == "zahlung"),
        "sparen":   sum(t["betrag"] for t in gefiltert if t["typ"] == "sparen"),
        "anzahl_transaktionen": len(gefiltert),
        "kategorien": {}
    }
    for t in gefiltert:
        kat = t.get("kategorie", "Sonstige") or "Sonstige"
        result["kategorien"].setdefault(kat, 0.0)
        result["kategorien"][kat] += t["betrag"]
    return result

@app.post("/reset")
def reset_all():
    transaktionen_liste.clear()
    belege_store.clear()
    return {"message": "Alle Daten wurden zurückgesetzt"}
