from __future__ import annotations

# === Standard ===
import os
import re
import uuid
import shutil
from io import BytesIO
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Optional, Dict, Any, List

# === Third-party ===
import numpy as np
import cv2
import fitz  # PyMuPDF

from fastapi import FastAPI, Query, UploadFile, File, Form, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import Transaktion, Beleg, Base
from database import engine, SessionLocal

# === App Initialisierung ===
app = FastAPI(title="Monetra Backend")

# ✅ CORS-Middleware muss direkt hierhin!
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "https://startling-souffle-cd2bcd.netlify.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Fehler-Logging-Middleware (nach CORS!)
import traceback

@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        traceback.print_exc()
        raise

# Rest deines Codes bleibt unverändert…

Base.metadata.create_all(bind=engine)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# === Datenbank-Session ===
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# === Hilfsfunktionen ===
def to_decimal2(value) -> Decimal:
    try:
        if isinstance(value, Decimal):
            d = value
        elif isinstance(value, (int, float)):
            d = Decimal(str(value))
        else:
            s = str(value).strip().replace(" ", "").replace("'", "").replace(",", ".")
            d = Decimal(s)
        return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")

def add_months_safe(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    mdays = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
             31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return d.replace(year=y, month=m, day=min(d.day, mdays))

def safe_filename(original: str) -> str:
    stem, ext = os.path.splitext(original or "")
    return f"{uuid.uuid4().hex}{(ext or '').lower() or '.bin'}"

# === QR Erkennung ===
QR_IBAN_RE = re.compile(r"\bCH\d{2}[0-9A-Z]{17}\b")
AMOUNT_RE = re.compile(r"\b\d+(?:[.,]\d{1,2})\b")
CURRENCY_RE = re.compile(r"\b(CHF|EUR)\b", re.I)
REFERENCE_RE = re.compile(r"\b(?:RF\d{2}[0-9A-Z]{1,21}|\d{10,27})\b")

def _read_qr_text_from_image(image_path: str) -> Optional[str]:
    img = cv2.imread(image_path)
    if img is None:
        return None
    det = cv2.QRCodeDetector()
    txt, pts, _ = det.detectAndDecode(img)
    return txt or None

def _pdf_first_page_to_png(pdf_path: str) -> Optional[str]:
    try:
        doc = fitz.open(pdf_path)
        if doc.page_count == 0:
            return None
        pix = doc[0].get_pixmap(dpi=200)
        tmp = UPLOAD_DIR / f"__tmp_{uuid.uuid4().hex}.png"
        pix.save(str(tmp))
        return str(tmp)
    except Exception:
        return None

def extract_qr_text(file_path: str, content_type: str) -> Optional[str]:
    if "pdf" in content_type.lower() or file_path.lower().endswith(".pdf"):
        tmp_img = _pdf_first_page_to_png(file_path)
        if not tmp_img:
            return None
        try:
            return _read_qr_text_from_image(tmp_img)
        finally:
            try:
                os.remove(tmp_img)
            except Exception:
                pass
    return _read_qr_text_from_image(file_path)

def parse_swiss_qr(qr_text: str) -> Dict[str, Any]:
    info = {"iban": None, "empfaenger": None, "betrag": None, "waehrung": None,
            "referenz": None, "zusatzinfo": None}
    if not qr_text:
        return info

    lines = [l.strip() for l in qr_text.splitlines() if l.strip()]

    m = QR_IBAN_RE.search(qr_text.replace(" ", ""))
    if m:
        info["iban"] = m.group(0)

    cur = CURRENCY_RE.search(qr_text)
    if cur:
        info["waehrung"] = cur.group(1).upper()

    amts = AMOUNT_RE.findall(qr_text)
    for a in amts:
        val = float(a.replace(",", "."))
        if 0 < val <= 1_000_000:
            info["betrag"] = val
            break

    ref = REFERENCE_RE.search(qr_text.replace(" ", ""))
    if ref:
        info["referenz"] = ref.group(0)

    if not info["empfaenger"]:
        for l in lines:
            if len(l) >= 3 and not QR_IBAN_RE.search(l.replace(" ", "")) and not CURRENCY_RE.search(l):
                info["empfaenger"] = l
                break

    if len(lines) >= 2:
        info["zusatzinfo"] = " / ".join(lines[-2:])

    return info

def build_transaction_suggestion(parsed: dict) -> dict:
    bezeichnung = parsed.get("empfaenger") or parsed.get("zusatzinfo") or "Rechnung"
    betrag = parsed.get("betrag")
    waehrung = (parsed.get("waehrung") or "CHF").upper()
    return {
        "typ": "zahlung",
        "bezeichnung": bezeichnung[:80],
        "betrag": float(betrag) if isinstance(betrag, (int, float)) else 0.0,
        "waehrung": waehrung,
        "kategorie": "Rechnungen",
        "datum": date.today().isoformat(),
        "wiederkehrend": False,
        "serie": None,
        "meta": {
            "iban": parsed.get("iban"),
            "referenz": parsed.get("referenz"),
            "zusatzinfo": parsed.get("zusatzinfo"),
        }
    }

# === Upload Rechnung ===
@app.post("/upload-rechnung")
async def upload_rechnung(
    file: UploadFile = File(...),
    transaktion_id: str = Form(""),
    beschreibung: str = Form(""),
):
    raw_name = file.filename or "upload"
    suffix = os.path.splitext(raw_name)[1].lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".pdf"):
        suffix = ".jpg"
    safe_name = f"{uuid.uuid4().hex}{suffix}"
    stored_path = UPLOAD_DIR / safe_name
    with stored_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    qr_text = extract_qr_text(str(stored_path), file.content_type or "")
    parsed = parse_swiss_qr(qr_text) if qr_text else {}
    suggestion = build_transaction_suggestion(parsed) if qr_text else None

    return {
        "ok": True,
        "filename": raw_name,
        "stored_as": safe_name,
        "content_type": file.content_type,
        "url": f"/uploads/{safe_name}",
        "qr_found": bool(qr_text),
        "qr_text": qr_text,
        "qr_info": parsed,
        "transaktion_id": transaktion_id or None,
        "beschreibung": beschreibung or "",
        "vorschlag": suggestion,
    }
...
# (Fortsetzung von oben)

from pydantic import BaseModel
from typing import Optional, Any

class TransaktionEingabe(BaseModel):
    typ: str
    bezeichnung: str
    betrag: Any  # wir normalisieren selbst via to_decimal2
    datum: str
    kategorie: Optional[str] = ""
    wiederkehrend: Optional[bool] = False
    beleg_id: Optional[str] = None


# =============================================================================
# Transaktionen (POST)
# =============================================================================

@app.post("/transaktion")
def add_transaktion(
    eingabe: TransaktionEingabe,
    db: Session = Depends(get_db)
):
    neu = eingabe.dict()
    neu["id"] = str(uuid.uuid4())
    neu["betrag"] = float(to_decimal2(neu.get("betrag")))
    neu["datum"] = datetime.strptime(neu["datum"], "%Y-%m-%d").date()

    neue_transaktion = Transaktion(**neu)
    db.add(neue_transaktion)

    if neu.get("wiederkehrend"):
        start = neu["datum"]
        for i in range(1, 12):
            nd = add_months_safe(start, i)
            kopie = neu.copy()
            kopie["id"] = str(uuid.uuid4())
            kopie["datum"] = nd
            neue_kopie = Transaktion(**kopie)
            db.add(neue_kopie)

    db.commit()
    return {"message": "Transaktion gespeichert", "id": neu["id"]}

# =============================================================================
# Transaktionen abrufen (GET)
# =============================================================================

@app.get("/transaktionen")
def get_transaktionen(
    monat: Optional[str] = None,
    nur_serie: bool = False,
    db: Session = Depends(get_db)
):
    query = db.query(Transaktion)
    if monat:
        try:
            y, m = map(int, monat.split("-"))
        except Exception:
            raise HTTPException(status_code=422, detail="Ungültiger Monat (YYYY-MM)")
        query = query.filter(
            Transaktion.datum >= date(y, m, 1),
            Transaktion.datum < add_months_safe(date(y, m, 1), 1)
        )
    if nur_serie:
        query = query.filter(Transaktion.wiederkehrend == True)

    result = query.all()
    return [{**t.__dict__, "betrag": float(t.betrag)} for t in result]

# =============================================================================
# Einzelne Transaktion abrufen
# =============================================================================

@app.get("/transaktion/{id}")
def get_transaktion_by_id(id: str, db: Session = Depends(get_db)):
    tx = db.get(Transaktion, id)
    if not tx:
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    return {**tx.__dict__, "betrag": float(tx.betrag)}

# =============================================================================
# Transaktion ändern
# =============================================================================

@app.put("/transaktion/{id}")
def update_transaktion(
    id: str,
    eingabe: TransaktionEingabe,
    alle_zukuenftig: bool = Query(False),
    db: Session = Depends(get_db)
):
    tx = db.get(Transaktion, id)
    if not tx:
        raise HTTPException(status_code=404, detail="Nicht gefunden")

    if alle_zukuenftig and tx.wiederkehrend:
        db.query(Transaktion).filter(
            Transaktion.wiederkehrend == True,
            Transaktion.bezeichnung == tx.bezeichnung,
            Transaktion.datum >= tx.datum
        ).delete()
        db.commit()

        neu = eingabe.dict()
        neu["id"] = str(uuid.uuid4())
        neu["betrag"] = float(to_decimal2(neu.get("betrag")))
        neu["datum"] = datetime.strptime(neu["datum"], "%Y-%m-%d").date()
        neue_tx = Transaktion(**neu)
        db.add(neue_tx)

        if neu.get("wiederkehrend"):
            start = neu["datum"]
            for i in range(1, 12):
                nd = add_months_safe(start, i)
                kopie = neu.copy()
                kopie["id"] = str(uuid.uuid4())
                kopie["datum"] = nd
                db.add(Transaktion(**kopie))

        db.commit()
        return {"message": "Serie aktualisiert"}

    # Nur einzelne Transaktion
    for key, val in eingabe.dict().items():
        if key == "betrag":
            val = float(to_decimal2(val))
        setattr(tx, key, val)

    db.commit()
    return {"message": "Transaktion aktualisiert"}

# =============================================================================
# Transaktion löschen
# =============================================================================

@app.delete("/transaktion/{id}")
def delete_transaktion(
    id: str,
    alle_zukuenftig: bool = Query(False),
    db: Session = Depends(get_db)
):
    tx = db.get(Transaktion, id)
    if not tx:
        raise HTTPException(status_code=404, detail="Nicht gefunden")

    if alle_zukuenftig and tx.wiederkehrend:
        db.query(Transaktion).filter(
            Transaktion.wiederkehrend == True,
            Transaktion.bezeichnung == tx.bezeichnung,
            Transaktion.datum >= tx.datum
        ).delete()
        db.commit()
        return {"message": "Serie gelöscht"}

    db.delete(tx)
    db.commit()
    return {"message": "Transaktion gelöscht"}

# =============================================================================
# Dashboard: Verfügbar
# =============================================================================

@app.get("/verfuegbar")
def get_verfuegbar(db: Session = Depends(get_db)):
    heute = datetime.today().date()
    verf = Decimal("0.00")
    alle = db.query(Transaktion).all()
    for t in alle:
        if t.datum <= heute:
            betrag = to_decimal2(t.betrag)
            if t.typ == "einnahme":
                verf += betrag
            else:
                verf -= betrag
    return {"verfuegbar": float(verf)}

# =============================================================================
# Dashboard: Nächste Zahlungen
# =============================================================================

@app.get("/naechste-zahlungen")
def get_all_future_payments(db: Session = Depends(get_db)):
    heute = datetime.today().date()
    future = []
    summe = Decimal("0.00")
    for t in db.query(Transaktion).filter(Transaktion.typ == "zahlung").all():
        if t.datum >= heute:
            betrag = to_decimal2(t.betrag)
            future.append({
                "name": t.bezeichnung,
                "datum": t.datum.isoformat(),
                "in_tagen": (t.datum - heute).days,
                "betrag": float(betrag),
            })
            summe += betrag
    return {"gesamt_betrag": float(summe), "zahlungen": sorted(future, key=lambda z: z["in_tagen"])}

# =============================================================================
# Monatsreport
# =============================================================================

@app.get("/monatsreport")
def monatsreport(monat: str, db: Session = Depends(get_db)):
    try:
        jahr, monat_zahl = map(int, monat.split("-"))
    except ValueError:
        raise HTTPException(status_code=422, detail="Ungültiges Format (YYYY-MM)")

    start = date(jahr, monat_zahl, 1)
    end = add_months_safe(start, 1)

    gefiltert = db.query(Transaktion).filter(
        Transaktion.datum >= start,
        Transaktion.datum < end
    ).all()

    result = {
        "einnahmen": 0.0,
        "ausgaben": 0.0,
        "zahlungen": 0.0,
        "sparen": 0.0,
        "anzahl_transaktionen": len(gefiltert),
        "kategorien": {},
    }
    for t in gefiltert:
        betrag = to_decimal2(t.betrag)
        if t.typ == "einnahme":
            result["einnahmen"] += float(betrag)
        elif t.typ == "ausgabe":
            result["ausgaben"] += float(betrag)
        elif t.typ == "zahlung":
            result["zahlungen"] += float(betrag)
        elif t.typ == "sparen":
            result["sparen"] += float(betrag)
        kat = t.kategorie or "Sonstige"
        result["kategorien"].setdefault(kat, 0.0)
        result["kategorien"][kat] += float(betrag)
    return result

# =============================================================================
# Reset
# =============================================================================

@app.post("/reset")
def reset_all(db: Session = Depends(get_db)):
    db.query(Transaktion).delete()
    db.query(Beleg).delete()
    db.commit()
    return {"message": "Alle Daten wurden zurückgesetzt"}

@app.get("/")
def read_root():
    return {"message": "Monetra Backend läuft!"}