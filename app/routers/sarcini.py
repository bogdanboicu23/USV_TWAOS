import sqlite3
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_utilizator_curent
from app.database import get_db
from app.schemas import SarcinaActualizare, SarcinaCreare

router = APIRouter(prefix="/sarcini", tags=["Sarcini"])

# Columns that are safe to use in ORDER BY. Validated explicitly to prevent
# SQL injection from user-supplied sort parameters.
_COLOANE_SORTARE_PERMISE = {"data_crearii", "prioritate", "data_limita"}


def _today_iso() -> str:
    return date.today().isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def _build_order_clause(sorteaza_dupa: Optional[str], ordine: str) -> str:
    """
    Produce a safe ORDER BY clause.

    `prioritate` requires special handling because the values are strings but
    carry a logical numeric ordering (scazuta < medie < ridicata). A CASE
    expression maps them to integers so SQLite sorts correctly.

    For `data_limita`, NULL rows are pushed to the end regardless of direction
    so incomplete tasks do not obscure dated ones.

    Both the column name and the direction are validated against whitelists
    before being interpolated — no user-supplied string ever reaches the SQL
    unvalidated.
    """
    sql_ordine = "ASC" if ordine.lower() == "asc" else "DESC"

    if sorteaza_dupa is None or sorteaza_dupa not in _COLOANE_SORTARE_PERMISE:
        return f"ORDER BY id {sql_ordine}"

    if sorteaza_dupa == "prioritate":
        return (
            f"ORDER BY CASE prioritate "
            f"WHEN 'scazuta' THEN 1 "
            f"WHEN 'medie' THEN 2 "
            f"WHEN 'ridicata' THEN 3 "
            f"ELSE 2 END {sql_ordine}"
        )

    if sorteaza_dupa == "data_limita":
        # `data_limita IS NULL` evaluates to 0 (false) or 1 (true), so
        # ordering by it first always places NULLs last.
        return f"ORDER BY data_limita IS NULL, data_limita {sql_ordine}"

    return f"ORDER BY {sorteaza_dupa} {sql_ordine}"


# ---------------------------------------------------------------------------
# GET /sarcini/statistici
# Must be declared BEFORE /{sarcina_id} to avoid FastAPI treating the literal
# string "statistici" as a path parameter value.
# ---------------------------------------------------------------------------

@router.get("/statistici")
def statistici_sarcini(
    utilizator: dict = Depends(get_utilizator_curent),
    db: sqlite3.Connection = Depends(get_db),
):
    """
    Returns aggregate statistics for the authenticated user's tasks:
    - total, finalizate, nefinalizate, depasite (overdue and not completed)
    - counts broken down by priority level
    """
    cur = db.cursor()
    cur.execute(
        "SELECT * FROM sarcini WHERE utilizator_id = ?",
        (utilizator["id"],),
    )
    toate = [_row_to_dict(row) for row in cur.fetchall()]

    today = _today_iso()

    total = len(toate)
    finalizate = sum(1 for s in toate if s["finalizata"])
    nefinalizate = total - finalizate
    depasite = sum(
        1
        for s in toate
        if not s["finalizata"]
        and s.get("data_limita")
        and s["data_limita"][:10] < today
    )

    dupa_prioritate = {"scazuta": 0, "medie": 0, "ridicata": 0}
    for sarcina in toate:
        prioritate = sarcina.get("prioritate") or "medie"
        if prioritate in dupa_prioritate:
            dupa_prioritate[prioritate] += 1

    return {
        "total": total,
        "finalizate": finalizate,
        "nefinalizate": nefinalizate,
        "depasite": depasite,
        "dupa_prioritate": dupa_prioritate,
    }


# ---------------------------------------------------------------------------
# GET /sarcini
# ---------------------------------------------------------------------------

@router.get("")
def lista_sarcini(
    doar_nefinalizate: bool = Query(False),
    sorteaza_dupa: Optional[Literal["data_crearii", "prioritate", "data_limita"]] = Query(
        None,
        description="Coloana după care se sortează rezultatele",
    ),
    ordine: Literal["asc", "desc"] = Query(
        "desc",
        description="Direcția de sortare: asc sau desc",
    ),
    utilizator: dict = Depends(get_utilizator_curent),
    db: sqlite3.Connection = Depends(get_db),
):
    cur = db.cursor()

    where_clause = "WHERE utilizator_id = ?"
    params: list = [utilizator["id"]]

    if doar_nefinalizate:
        where_clause += " AND finalizata = 0"

    order_clause = _build_order_clause(sorteaza_dupa, ordine)

    cur.execute(
        f"SELECT * FROM sarcini {where_clause} {order_clause}",
        params,
    )
    return [_row_to_dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# GET /sarcini/{sarcina_id}
# ---------------------------------------------------------------------------

@router.get("/{sarcina_id}")
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
    return _row_to_dict(sarcina)


# ---------------------------------------------------------------------------
# POST /sarcini
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
def creaza_sarcina(
    date: SarcinaCreare,
    utilizator: dict = Depends(get_utilizator_curent),
    db: sqlite3.Connection = Depends(get_db),
):
    data_crearii = datetime.now(timezone.utc).isoformat()
    cur = db.cursor()
    cur.execute(
        """
        INSERT INTO sarcini
            (titlu, descriere, finalizata, data_crearii, utilizator_id,
             prioritate, data_limita, categorie)
        VALUES (?, ?, 0, ?, ?, ?, ?, ?)
        """,
        (
            date.titlu,
            date.descriere,
            data_crearii,
            utilizator["id"],
            date.prioritate.value,
            date.data_limita,
            date.categorie,
        ),
    )
    db.commit()
    return {
        "id": cur.lastrowid,
        "titlu": date.titlu,
        "descriere": date.descriere,
        "finalizata": 0,
        "data_crearii": data_crearii,
        "utilizator_id": utilizator["id"],
        "prioritate": date.prioritate.value,
        "data_limita": date.data_limita,
        "categorie": date.categorie,
    }


# ---------------------------------------------------------------------------
# PUT /sarcini/{sarcina_id}
# ---------------------------------------------------------------------------

@router.put("/{sarcina_id}")
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

    sarcina = _row_to_dict(sarcina)

    if date.titlu is not None:
        sarcina["titlu"] = date.titlu
    if date.descriere is not None:
        sarcina["descriere"] = date.descriere
    if date.finalizata is not None:
        sarcina["finalizata"] = int(date.finalizata)
    if date.prioritate is not None:
        sarcina["prioritate"] = date.prioritate.value
    if date.data_limita is not None:
        sarcina["data_limita"] = date.data_limita
    if date.categorie is not None:
        sarcina["categorie"] = date.categorie

    cur.execute(
        """
        UPDATE sarcini
        SET titlu = ?, descriere = ?, finalizata = ?,
            prioritate = ?, data_limita = ?, categorie = ?
        WHERE id = ? AND utilizator_id = ?
        """,
        (
            sarcina["titlu"],
            sarcina["descriere"],
            sarcina["finalizata"],
            sarcina["prioritate"],
            sarcina["data_limita"],
            sarcina["categorie"],
            sarcina_id,
            utilizator["id"],
        ),
    )
    db.commit()
    return sarcina


# ---------------------------------------------------------------------------
# PATCH /sarcini/{sarcina_id}/finalizeaza
# ---------------------------------------------------------------------------

@router.patch("/{sarcina_id}/finalizeaza")
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

    sarcina = _row_to_dict(sarcina)
    valoare_noua = 0 if sarcina["finalizata"] else 1
    cur.execute(
        "UPDATE sarcini SET finalizata = ? WHERE id = ? AND utilizator_id = ?",
        (valoare_noua, sarcina_id, utilizator["id"]),
    )
    db.commit()
    sarcina["finalizata"] = valoare_noua
    return sarcina


# ---------------------------------------------------------------------------
# DELETE /sarcini/{sarcina_id}
# ---------------------------------------------------------------------------

@router.delete("/{sarcina_id}")
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