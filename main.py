from __future__ import annotations

# --- Standard ---
import os
import re
import uuid
import shutil
from io import BytesIO
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Optional, Dict, Any, List

# --- Third-party ---
import numpy as np
import cv2
import fitz  # PyMuPDF

from fastapi import FastAPI, Query, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# =============================================================================
# App & CORS
# =============================================================================

app = FastAPI(title="Monetra Backend")

ALLOWED_ORIGINS = [
    "https://startling-souffle-cd2bcd.netlify.app",  # Netlify
    "http://127.0.0.1:5500",                          # VS Code Live Server
    "http://localhost:5500",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Upload-Verzeichnis (einmalig mounten)
# =============================================================================

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# =============================================================================
# Utils
# =============================================================================

def to_decimal2(value) -> Decimal:
    """Normalisiert '140,45'/'140.45'/140 → Decimal(2) mit kaufm. Rundung."""
    if value is None:
        return Decimal("0.00")
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
    """Fügt Monate sicher hinzu (28/29/30/31)."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    mdays = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
             31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return d.replace(year=y, month=m, day=min(d.day, mdays))

def safe_filename(original: str) -> str:
    stem, ext = os.path.splitext(original or "")
    return f"{uuid.uuid4().hex}{(ext or '').lower() or '.bin'}"

# =============================================================================
# In-Memory Stores (Dev)
# =============================================================================

transaktionen_liste: List[Dict[str, Any]] = []
belege_store: Dict[str, Dict[str, Any]] = {}  # beleg_id -> blob

# =============================================================================
# QR / PDF Utilities
# =============================================================================

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
    ct = (content_type or "").lower()
    if "pdf" in ct or file_path.lower().endswith(".pdf"):
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
    info = {"iban": None, "empfaenger": None, "betrag": None,
            "waehrung": None, "referenz": None, "zusatzinfo": None}
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

# =============================================================================
# Models
# =============================================================================

class TransaktionEingabe(BaseModel):
    typ: str
    bezeichnung: str
    betrag: Any     # wir normalisieren selbst via to_decimal2
    datum: str
    kategorie: Optional[str] = ""
    wiederkehrend: Optional[bool] = False
    beleg_id: Optional[str] = None

# =============================================================================
# Root
# =============================================================================

@app.get("/")
def read_root():
    return {"message": "Monetra Backend läuft!"}

# =============================================================================
# Belege (in-memory)
# =============================================================================

MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB

@app.post("/upload")
async def upload_beleg(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Datei zu groß (max. 5MB)")
    beleg_id = str(uuid.uuid4())
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
    for t in transaktionen_liste:
        if t.get("beleg_id") == beleg_id:
            t["beleg_id"] = None
    del belege_store[beleg_id]
    return {"message": "Beleg gelöscht"}

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

# =============================================================================
# Transaktionen
# =============================================================================

@app.post("/transaktion")
def add_transaktion(eingabe: TransaktionEingabe):
    tx = eingabe.dict()
    tx["betrag"] = to_decimal2(tx.get("betrag"))
    tx["id"] = str(uuid.uuid4())
    transaktionen_liste.append(tx)

    if tx.get("wiederkehrend"):
        start = datetime.strptime(tx["datum"], "%Y-%m-%d").date()
        for i in range(1, 12):
            nd = add_months_safe(start, i)
            kopie = tx.copy()
            kopie["id"] = str(uuid.uuid4())
            kopie["datum"] = nd.isoformat()
            transaktionen_liste.append(kopie)

    return {"message": "Transaktion gespeichert", "id": tx["id"]}

@app.get("/transaktionen")
def get_transaktionen(monat: Optional[str] = None, nur_serie: bool = False):
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

    # Beträge als float zurückgeben
    return {"transaktionen": [
        {**t, "betrag": float(t["betrag"]) if isinstance(t.get("betrag"), Decimal) else t.get("betrag")}
        for t in result
    ]}

@app.get("/transaktion/{id}")
def get_transaktion_by_id(id: str):
    for t in transaktionen_liste:
        if t["id"] == id:
            out = {**t}
            if isinstance(out.get("betrag"), Decimal):
                out["betrag"] = float(out["betrag"])
            return out
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
        # Neue Serie
        neu = eingabe.dict()
        neu["betrag"] = to_decimal2(neu.get("betrag"))
        neu["id"] = str(uuid.uuid4())
        transaktionen_liste.append(neu)

        if neu.get("wiederkehrend"):
            start = datetime.strptime(neu["datum"], "%Y-%m-%d").date()
            for i in range(1, 12):
                nd = add_months_safe(start, i)
                kopie = neu.copy()
                kopie["id"] = str(uuid.uuid4())
                kopie["datum"] = nd.isoformat()
                transaktionen_liste.append(kopie)
        return {"message": "Serie aktualisiert"}

    # Nur diese Transaktion
    for idx, t in enumerate(transaktionen_liste):
        if t["id"] == id:
            neu = eingabe.dict()
            neu["betrag"] = to_decimal2(neu.get("betrag"))
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

    transaktionen_liste[:] = [t for t in transaktionen_liste if t["id"] != id]
    return {"message": "Transaktion gelöscht"}

# =============================================================================
# Dashboard
# =============================================================================

@app.get("/verfuegbar")
def get_verfuegbar():
    heute = datetime.today().date()
    verf = Decimal("0.00")
    for t in transaktionen_liste:
        datum = datetime.strptime(t["datum"], "%Y-%m-%d").date()
        betrag = to_decimal2(t.get("betrag"))
        if datum <= heute:
            if t["typ"] == "einnahme":
                verf += betrag
            else:
                verf -= betrag
    return {"verfuegbar": float(verf)}

@app.get("/naechste-zahlungen")
def get_all_future_payments():
    heute = datetime.today().date()
    future = []
    summe = Decimal("0.00")
    for t in transaktionen_liste:
        if t["typ"] == "zahlung":
            zahl_datum = datetime.strptime(t["datum"], "%Y-%m-%d").date()
            if zahl_datum >= heute:
                betrag = to_decimal2(t.get("betrag"))
                future.append({
                    "name": t["bezeichnung"],
                    "datum": zahl_datum.isoformat(),
                    "in_tagen": (zahl_datum - heute).days,
                    "betrag": float(betrag),
                })
                summe += betrag
    return {"gesamt_betrag": float(summe), "zahlungen": sorted(future, key=lambda z: z["in_tagen"])}

@app.get("/monatsreport")
def monatsreport(monat: str):
    try:
        jahr, monat_zahl = map(int, monat.split("-"))
    except ValueError:
        raise HTTPException(status_code=422, detail="Ungültiges Format (YYYY-MM)")

    gefiltert = [
        {**t, "betrag": to_decimal2(t.get("betrag"))}
        for t in transaktionen_liste
        if datetime.strptime(t["datum"], "%Y-%m-%d").year == jahr and
           datetime.strptime(t["datum"], "%Y-%m-%d").month == monat_zahl
    ]

    result = {
        "einnahmen": float(sum(t["betrag"] for t in gefiltert if t["typ"] == "einnahme")),
        "ausgaben":  float(sum(t["betrag"] for t in gefiltert if t["typ"] == "ausgabe")),
        "zahlungen": float(sum(t["betrag"] for t in gefiltert if t["typ"] == "zahlung")),
        "sparen":    float(sum(t["betrag"] for t in gefiltert if t["typ"] == "sparen")),
        "anzahl_transaktionen": len(gefiltert),
        "kategorien": {},
    }
    for t in gefiltert:
        kat = t.get("kategorie", "Sonstige") or "Sonstige"
        result["kategorien"].setdefault(kat, 0.0)
        result["kategorien"][kat] += float(t["betrag"])
    return result

# =============================================================================
# Reset
# =============================================================================

@app.post("/reset")
def reset_all():
    transaktionen_liste.clear()
    belege_store.clear()
    return {"message": "Alle Daten wurden zurückgesetzt"}
