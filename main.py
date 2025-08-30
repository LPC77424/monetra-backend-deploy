from fastapi import FastAPI, Query, UploadFile, File, HTTPException
from fastapi import UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import uuid4
from io import BytesIO
import uuid
import shutil
import os
from typing import Optional, Tuple, Dict, Any
from fastapi.responses import JSONResponse
import numpy as np
import cv2
import fitz #PyMuPDF


app = FastAPI()

# Upload-Ordner einrichten
UPLOAD_DIR = os.path.join( os.getcwd (), "uploads")
os.makedirs (UPLOAD_DIR, exist_ok=True)

from fastapi.staticfiles import StaticFiles
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# -------- Helpers: Speichern & QR-Scan --------
def _safe_name(original: str) -> str:
    import os, uuid
    stem, ext = os.path.splitext(original)
    return f"{uuid.uuid4().hex}{ext.lower()}"

def _save_upload(file: UploadFile) -> str:
    safe_name = _safe_name(file.filename)
    target = os.path.join(UPLOAD_DIR, safe_name)
    with open(target, "wb") as out:
        shutil.copyfileobj(file.file, out)
    return target  # absoluter Pfad

def _qr_from_image_np(img_bgr: np.ndarray) -> Optional[str]:
    detector = cv2.QRCodeDetector()
    data, points, _ = detector.detectAndDecode(img_bgr)
    if points is not None and data:
        return data.strip()
    return None

def _pdf_first_page_to_image(pdf_path: str) -> Optional[np.ndarray]:
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            return None
        page = doc[0]
        pix = page.get_pixmap(dpi=200, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)  # RGB -> BGR
        return img_bgr
    except Exception:
        return None

def _image_file_to_np_bgr(path: str) -> Optional[np.ndarray]:
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    return img if img is not None else None

def _maybe_parse_swiss_qr(raw: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"raw": raw}
    if raw.startswith("SPC"):
        # sehr einfache Heuristik: Betrag + Währung herausziehen
        import re
        m_amt = re.search(r"(\d+\.\d{2})", raw)
        if m_amt:
            try:
                out["amount"] = float(m_amt.group(1))
            except Exception:
                pass
        if "CHF" in raw:
            out["currency"] = "CHF"
        elif "EUR" in raw:
            out["currency"] = "EUR"
        out["format"] = "swiss-qr-guess"
    return out

@app.post("/upload-rechnung")
async def upload_rechnung(
    file: UploadFile = File(..., description="PDF, JPG, PNG"),
    transaktion_id: Optional[str] = Form(None),
    beschreibung: str = Form(""),
):
    saved_path = _save_upload(file)
    rel_url = f"/uploads/{os.path.basename(saved_path)}"
    content_type = file.content_type or ""
    qr_text = None

    if content_type.startswith("image/"):
        img = _image_file_to_np_bgr(saved_path)
        if img is not None:
            qr_text = _qr_from_image_np(img)
    elif content_type == "application/pdf" or saved_path.lower().endswith(".pdf"):
        img = _pdf_first_page_to_image(saved_path)
        if img is not None:
            qr_text = _qr_from_image_np(img)

    qr_info = _maybe_parse_swiss_qr(qr_text) if qr_text else {}

    return JSONResponse({
        "ok": True,
        "filename": file.filename,
        "stored_as": os.path.basename(saved_path),
        "content_type": content_type,
        "url": rel_url,
        "qr_found": bool(qr_text),
        "qr_text": qr_text,
        "qr_info": qr_info,
        "transaktion_id": transaktion_id,
        "beschreibung": beschreibung,
    })

# --- Uploads & CORS für Quittungen -----------------------------------------
try:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5500",
            "http://localhost:5500",
            "https://startling-souffle-cd2bcd.netlify.app",  # <-- DEINE Netlify-URL
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
except Exception:
    pass  # Falls schon CORS aktiv ist

# Upload-Verzeichnis + statische Auslieferung
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

def _attach_receipt_to_transaction(transaktion_id: str, url: str):
    """
    Hänge die Beleg-URL an deine Transaktion an.
    Hier erstmal No-Op, damit nichts bricht.
    Später an deine Datenstruktur anpassen.
    """
    # Beispiel (nur falls du eine TRANSAKTIONEN-Liste mit dicts hättest):
    # for tx in TRANSAKTIONEN:
    #     if tx["id"] == transaktion_id:
    #         tx["beleg_url"] = url
    #         break
    return

@app.post("/upload-quittung")
def upload_quittung(
    file: UploadFile = File(...),
    transaktion_id: str = Form(...),
    beschreibung: str = Form(""),
):
    # Dateityp prüfen
    if not file.filename:
        raise HTTPException(status_code=400, detail="Datei fehlt.")
    if file.content_type not in {"image/jpeg", "image/png", "application/pdf"}:
        raise HTTPException(status_code=415, detail="Nur JPG, PNG oder PDF erlaubt.")

    # Eindeutiger Dateiname
    suffix = Path(file.filename).suffix.lower()
    safe_name = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}{suffix}"
    target = UPLOAD_DIR / safe_name

    # Speichern
    with target.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    rel_url = f"/uploads/{safe_name}"

    # Optional: der Transaktion zuordnen (aktuell No-Op)
    try:
        _attach_receipt_to_transaction(transaktion_id, rel_url)
    except Exception:
        pass

    return {
        "ok": True,
        "filename": file.filename,
        "stored_as": safe_name,
        "content_type": file.content_type,
        "url": rel_url,
        "transaktion_id": transaktion_id,
        "beschreibung": beschreibung,
    }
# ---------------------------------------------------------------------------


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
