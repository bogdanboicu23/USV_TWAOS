import sqlite3
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import ALGORITHM, EXPIRARE_TOKEN_MINUTE, SECRET_KEY
from app.database import get_db


def hash_parola(parola: str) -> str:
    return bcrypt.hashpw(parola.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verifica_parola(parola: str, parola_hash: str) -> bool:
    return bcrypt.checkpw(parola.encode("utf-8"), parola_hash.encode("utf-8"))


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
        sub = payload.get("sub")
        if sub is None:
            raise HTTPException(status_code=401, detail="Token invalid")
        utilizator_id = int(sub)
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
