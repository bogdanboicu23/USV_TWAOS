"""
Gestionar de Sarcini — FastAPI Backend
TAOS Labs 02–05 (cu bonusuri)
"""

import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from pydantic import BaseModel, Field, field_validator

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-schimba-in-productie")
ALGORITHM = os.environ.get("ALGORITHM", "HS256")
EXPIRARE_TOKEN_MINUTE = int(os.environ.get("EXPIRARE_TOKEN_MINUTE", "60"))
DATABASE_PATH = os.environ.get("DATABASE_PATH", "sarcini.db")

# ── DB setup ──────────────────────────────────────────────────────────────────

def init_db():
    con = sqlite3.connect(DATABASE_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS utilizatori (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nume TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            parola_hash TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sarcini (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titlu TEXT NOT NULL,
            descriere TEXT DEFAULT '',
            finalizata INTEGER DEFAULT 0,
            data_crearii TEXT NOT NULL,
            utilizator_id INTEGER NOT NULL,
            FOREIGN KEY (utilizator_id) REFERENCES utilizatori(id)
        )
    """)
    con.commit()
    con.close()


def get_db():
    con = sqlite3.connect(DATABASE_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Gestionar de Sarcini",
    description="API pentru gestionarea sarcinilor — TAOS Labs 02-05",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS middleware ───────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ──────────────────────────────────────────────────────────

class UtilizatorInregistrare(BaseModel):
    nume: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., max_length=200)
    parola: str = Field(..., min_length=6, max_length=200)

    @field_validator("email")
    @classmethod
    def valideaza_email(cls, v: str) -> str:
        pattern = r"^[\w\.\+\-]+@[\w\-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, v):
            raise ValueError("Adresa de email nu este validă")
        return v.lower()


class UtilizatorAutentificare(BaseModel):
    email: str
    parola: str


class SarcinaCreare(BaseModel):
    titlu: str = Field(..., min_length=1, max_length=200)
    descriere: str = Field("", max_length=2000)


class SarcinaActualizare(BaseModel):
    titlu: str = Field(None, min_length=1, max_length=200)
    descriere: str = Field(None, max_length=2000)
    finalizata: bool = None

# ── Auth utilities ────────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_parola(parola: str) -> str:
    return pwd_context.hash(parola)


def verifica_parola(parola: str, parola_hash: str) -> bool:
    return pwd_context.verify(parola, parola_hash)


def creaza_token(data: dict) -> str:
    payload = data.copy()
    expira = datetime.now(timezone.utc) + timedelta(minutes=EXPIRARE_TOKEN_MINUTE)
    payload.update({"exp": expira})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


security = HTTPBearer()


def get_utilizator_curent(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: sqlite3.Connection = Depends(get_db),
):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        utilizator_id: int = payload.get("sub")
        if utilizator_id is None:
            raise HTTPException(status_code=401, detail="Token invalid")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirat")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalid")

    cur = db.cursor()
    cur.execute("SELECT id, nume, email FROM utilizatori WHERE id = ?", (utilizator_id,))
    utilizator = cur.fetchone()
    if utilizator is None:
        raise HTTPException(status_code=401, detail="Utilizator negăsit")
    return dict(utilizator)

# ── Auth endpoints ────────────────────────────────────────────────────────────

@app.post("/inregistrare", status_code=status.HTTP_201_CREATED)
def inregistrare(date: UtilizatorInregistrare, db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT id FROM utilizatori WHERE email = ?", (date.email,))
    if cur.fetchone():
        raise HTTPException(status_code=400, detail="Email deja înregistrat")

    parola_hash = hash_parola(date.parola)
    cur.execute(
        "INSERT INTO utilizatori (nume, email, parola_hash) VALUES (?, ?, ?)",
        (date.nume, date.email, parola_hash),
    )
    db.commit()
    return {"mesaj": "Utilizator înregistrat cu succes", "id": cur.lastrowid}


@app.post("/autentificare")
def autentificare(date: UtilizatorAutentificare, db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT id, nume, email, parola_hash FROM utilizatori WHERE email = ?", (date.email.lower(),))
    utilizator = cur.fetchone()
    if not utilizator or not verifica_parola(date.parola, utilizator["parola_hash"]):
        raise HTTPException(status_code=401, detail="Email sau parolă incorectă")

    token = creaza_token({"sub": utilizator["id"], "email": utilizator["email"]})
    return {"token": token, "tip": "Bearer", "nume": utilizator["nume"]}

# ── User endpoint ─────────────────────────────────────────────────────────────

@app.get("/utilizatori/eu")
def profil_utilizator(utilizator: dict = Depends(get_utilizator_curent)):
    return utilizator

# ── Task CRUD endpoints ──────────────────────────────────────────────────────

@app.get("/sarcini")
def lista_sarcini(
    doar_nefinalizate: bool = Query(False),
    utilizator: dict = Depends(get_utilizator_curent),
    db: sqlite3.Connection = Depends(get_db),
):
    cur = db.cursor()
    if doar_nefinalizate:
        cur.execute(
            "SELECT * FROM sarcini WHERE utilizator_id = ? AND finalizata = 0 ORDER BY id DESC",
            (utilizator["id"],),
        )
    else:
        cur.execute(
            "SELECT * FROM sarcini WHERE utilizator_id = ? ORDER BY id DESC",
            (utilizator["id"],),
        )
    return [dict(row) for row in cur.fetchall()]


@app.get("/sarcini/{sarcina_id}")
def obtine_sarcina(
    sarcina_id: int,
    utilizator: dict = Depends(get_utilizator_curent),
    db: sqlite3.Connection = Depends(get_db),
):
    cur = db.cursor()
    cur.execute(
        "SELECT * FROM sarcini WHERE id = ? AND utilizator_id = ?",
        (sarcina_id, utilizator["id"]),
    )
    sarcina = cur.fetchone()
    if not sarcina:
        raise HTTPException(status_code=404, detail="Sarcina nu a fost găsită")
    return dict(sarcina)


@app.post("/sarcini", status_code=status.HTTP_201_CREATED)
def creaza_sarcina(
    date: SarcinaCreare,
    utilizator: dict = Depends(get_utilizator_curent),
    db: sqlite3.Connection = Depends(get_db),
):
    data_crearii = datetime.now(timezone.utc).isoformat()
    cur = db.cursor()
    cur.execute(
        "INSERT INTO sarcini (titlu, descriere, finalizata, data_crearii, utilizator_id) VALUES (?, ?, 0, ?, ?)",
        (date.titlu, date.descriere, data_crearii, utilizator["id"]),
    )
    db.commit()
    return {
        "id": cur.lastrowid,
        "titlu": date.titlu,
        "descriere": date.descriere,
        "finalizata": 0,
        "data_crearii": data_crearii,
        "utilizator_id": utilizator["id"],
    }


@app.put("/sarcini/{sarcina_id}")
def actualizeaza_sarcina(
    sarcina_id: int,
    date: SarcinaActualizare,
    utilizator: dict = Depends(get_utilizator_curent),
    db: sqlite3.Connection = Depends(get_db),
):
    cur = db.cursor()
    cur.execute(
        "SELECT * FROM sarcini WHERE id = ? AND utilizator_id = ?",
        (sarcina_id, utilizator["id"]),
    )
    sarcina = cur.fetchone()
    if not sarcina:
        raise HTTPException(status_code=404, detail="Sarcina nu a fost găsită")

    sarcina = dict(sarcina)
    if date.titlu is not None:
        sarcina["titlu"] = date.titlu
    if date.descriere is not None:
        sarcina["descriere"] = date.descriere
    if date.finalizata is not None:
        sarcina["finalizata"] = int(date.finalizata)

    cur.execute(
        "UPDATE sarcini SET titlu = ?, descriere = ?, finalizata = ? WHERE id = ? AND utilizator_id = ?",
        (sarcina["titlu"], sarcina["descriere"], sarcina["finalizata"], sarcina_id, utilizator["id"]),
    )
    db.commit()
    return sarcina


@app.patch("/sarcini/{sarcina_id}/finalizeaza")
def finalizeaza_sarcina(
    sarcina_id: int,
    utilizator: dict = Depends(get_utilizator_curent),
    db: sqlite3.Connection = Depends(get_db),
):
    cur = db.cursor()
    cur.execute(
        "SELECT * FROM sarcini WHERE id = ? AND utilizator_id = ?",
        (sarcina_id, utilizator["id"]),
    )
    sarcina = cur.fetchone()
    if not sarcina:
        raise HTTPException(status_code=404, detail="Sarcina nu a fost găsită")

    cur.execute(
        "UPDATE sarcini SET finalizata = 1 WHERE id = ? AND utilizator_id = ?",
        (sarcina_id, utilizator["id"]),
    )
    db.commit()
    sarcina = dict(sarcina)
    sarcina["finalizata"] = 1
    return sarcina


@app.delete("/sarcini/{sarcina_id}")
def sterge_sarcina(
    sarcina_id: int,
    utilizator: dict = Depends(get_utilizator_curent),
    db: sqlite3.Connection = Depends(get_db),
):
    cur = db.cursor()
    cur.execute(
        "SELECT id FROM sarcini WHERE id = ? AND utilizator_id = ?",
        (sarcina_id, utilizator["id"]),
    )
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Sarcina nu a fost găsită")

    cur.execute(
        "DELETE FROM sarcini WHERE id = ? AND utilizator_id = ?",
        (sarcina_id, utilizator["id"]),
    )
    db.commit()
    return {"mesaj": "Sarcina a fost ștearsă"}

# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/healthz")
def health_check():
    return {"status": "ok"}

# ── Static files (must be LAST) ──────────────────────────────────────────────

app.mount("/", StaticFiles(directory="static", html=True), name="static")
