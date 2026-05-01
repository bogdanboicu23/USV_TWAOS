import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import creaza_token, get_utilizator_curent, hash_parola, verifica_parola
from app.database import get_db
from app.schemas import UtilizatorAutentificare, UtilizatorInregistrare

router = APIRouter(tags=["Autentificare"])


@router.post("/inregistrare", status_code=status.HTTP_201_CREATED)
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


@router.post("/autentificare")
def autentificare(date: UtilizatorAutentificare, db: sqlite3.Connection = Depends(get_db)):
    cur = db.cursor()
    cur.execute("SELECT id, nume, email, parola_hash FROM utilizatori WHERE email = ?", (date.email.lower(),))
    utilizator = cur.fetchone()
    if not utilizator or not verifica_parola(date.parola, utilizator["parola_hash"]):
        raise HTTPException(status_code=401, detail="Email sau parolă incorectă")

    token = creaza_token({"sub": str(utilizator["id"]), "email": utilizator["email"]})
    return {"token": token, "tip": "Bearer", "nume": utilizator["nume"]}


@router.get("/utilizatori/eu")
def profil_utilizator(utilizator: dict = Depends(get_utilizator_curent)):
    return utilizator
