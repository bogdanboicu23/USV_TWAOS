"""
Comprehensive unit tests for the Gestionar de Sarcini FastAPI application.

Strategy
--------
- Each test function gets a fresh in-memory SQLite database via the `client`
  fixture, guaranteeing full isolation — no test touches the production
  `sarcini.db` file.
- `get_db` is overridden to inject the per-test in-memory connection.  The
  app's lifespan `init_db()` call would write to the real DATABASE_PATH, so
  we initialise the schema manually on the in-memory connection instead and
  patch `init_db` to a no-op for the duration of each test.
- The `StaticFiles` mount on "/" uses `app.router.routes` (a plain list)
  which is temporarily slimmed down so the test process does not require the
  `static/` directory to be present in the working directory.
- Helper functions (`register_and_login`, `create_task`) keep individual test
  bodies short and focused on a single behaviour.
"""

import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.database as database_module
from app.database import get_db
from app.main import app

# ---------------------------------------------------------------------------
# Full schema — kept in sync with app/database.py including all migrations
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS utilizatori (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nume TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    parola_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sarcini (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titlu TEXT NOT NULL,
    descriere TEXT DEFAULT '',
    finalizata INTEGER DEFAULT 0,
    data_crearii TEXT NOT NULL,
    utilizator_id INTEGER NOT NULL,
    prioritate TEXT NOT NULL DEFAULT 'medie',
    data_limita TEXT DEFAULT NULL,
    categorie TEXT DEFAULT NULL,
    FOREIGN KEY (utilizator_id) REFERENCES utilizatori(id)
);
"""


def _build_in_memory_db() -> sqlite3.Connection:
    """Return a fully initialised, isolated in-memory SQLite connection."""
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA_SQL)
    con.commit()
    return con


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """
    Yield a TestClient backed by a fresh in-memory database.

    Three things happen before handing the client to the test:
    1. `init_db` is patched to a no-op so the lifespan hook does not touch the
       real database file.
    2. `get_db` is overridden to yield the per-test in-memory connection.
    3. The StaticFiles mount (name="static") is temporarily removed from
       app.router.routes so TestClient startup does not require the static/
       directory to be accessible from whatever the current working directory is.
    """
    test_db = _build_in_memory_db()

    def override_get_db():
        try:
            yield test_db
        finally:
            pass  # fixture owns the connection lifetime

    # Stash the StaticFiles mount and remove it for the duration of this test.
    original_router_routes = list(app.router.routes)
    app.router.routes[:] = [
        r for r in app.router.routes if getattr(r, "name", None) != "static"
    ]

    app.dependency_overrides[get_db] = override_get_db

    with patch.object(database_module, "init_db", return_value=None):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    # Teardown — restore original state
    app.dependency_overrides.pop(get_db, None)
    app.router.routes[:] = original_router_routes
    test_db.close()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def register_and_login(
    client: TestClient,
    email: str,
    password: str,
    name: str = "Test User",
) -> str:
    """Register a user and return their Bearer token."""
    client.post(
        "/inregistrare",
        json={"nume": name, "email": email, "parola": password},
    )
    response = client.post(
        "/autentificare",
        json={"email": email, "parola": password},
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_task(
    client: TestClient,
    token: str,
    title: str = "Test task",
    description: str = "",
) -> dict:
    """Create a task and return the response JSON."""
    response = client.post(
        "/sarcini",
        json={"titlu": title, "descriere": description},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ===========================================================================
# 1. Authentication tests
# ===========================================================================

class TestInregistrare:
    """POST /inregistrare"""

    def test_register_new_user_successfully(self, client):
        response = client.post(
            "/inregistrare",
            json={"nume": "Ana Popescu", "email": "ana@example.com", "parola": "parola123"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["mesaj"] == "Utilizator înregistrat cu succes"
        assert isinstance(body["id"], int)

    def test_register_assigns_incrementing_ids(self, client):
        r1 = client.post(
            "/inregistrare",
            json={"nume": "User One", "email": "one@example.com", "parola": "parola123"},
        )
        r2 = client.post(
            "/inregistrare",
            json={"nume": "User Two", "email": "two@example.com", "parola": "parola123"},
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r2.json()["id"] > r1.json()["id"]

    def test_register_with_duplicate_email_fails(self, client):
        payload = {"nume": "Ana Popescu", "email": "dup@example.com", "parola": "parola123"}
        client.post("/inregistrare", json=payload)
        response = client.post("/inregistrare", json=payload)
        assert response.status_code == 400
        assert "deja" in response.json()["detail"].lower()

    def test_register_duplicate_email_is_case_insensitive(self, client):
        """The email validator lowercases input, so mixed-case duplicates must be rejected."""
        client.post(
            "/inregistrare",
            json={"nume": "Ana", "email": "Ana@Example.COM", "parola": "parola123"},
        )
        response = client.post(
            "/inregistrare",
            json={"nume": "Ana", "email": "ana@example.com", "parola": "parola123"},
        )
        assert response.status_code == 400

    def test_register_with_invalid_email_fails(self, client):
        response = client.post(
            "/inregistrare",
            json={"nume": "Ana Popescu", "email": "not-an-email", "parola": "parola123"},
        )
        assert response.status_code == 422

    def test_register_with_email_missing_tld_fails(self, client):
        response = client.post(
            "/inregistrare",
            json={"nume": "Ana", "email": "ana@example", "parola": "parola123"},
        )
        assert response.status_code == 422

    def test_register_with_short_password_fails(self, client):
        """Password minimum length is 6 characters."""
        response = client.post(
            "/inregistrare",
            json={"nume": "Ana Popescu", "email": "ana@example.com", "parola": "abc"},
        )
        assert response.status_code == 422

    def test_register_with_password_at_minimum_length_succeeds(self, client):
        """Exactly 6 characters must be accepted."""
        response = client.post(
            "/inregistrare",
            json={"nume": "Ana Popescu", "email": "ana@example.com", "parola": "abc123"},
        )
        assert response.status_code == 201

    def test_register_with_short_name_fails(self, client):
        """Name minimum length is 2 characters."""
        response = client.post(
            "/inregistrare",
            json={"nume": "A", "email": "ana@example.com", "parola": "parola123"},
        )
        assert response.status_code == 422

    def test_register_missing_required_fields_fails(self, client):
        response = client.post("/inregistrare", json={"email": "ana@example.com"})
        assert response.status_code == 422


class TestAutentificare:
    """POST /autentificare"""

    def test_login_with_correct_credentials_returns_token(self, client):
        client.post(
            "/inregistrare",
            json={"nume": "Ion", "email": "ion@example.com", "parola": "parola123"},
        )
        response = client.post(
            "/autentificare",
            json={"email": "ion@example.com", "parola": "parola123"},
        )
        assert response.status_code == 200
        body = response.json()
        assert "token" in body
        assert body["tip"] == "Bearer"
        assert body["nume"] == "Ion"

    def test_login_with_wrong_password_fails(self, client):
        client.post(
            "/inregistrare",
            json={"nume": "Ion", "email": "ion@example.com", "parola": "parola123"},
        )
        response = client.post(
            "/autentificare",
            json={"email": "ion@example.com", "parola": "wrong-password"},
        )
        assert response.status_code == 401

    def test_login_with_nonexistent_email_fails(self, client):
        response = client.post(
            "/autentificare",
            json={"email": "ghost@example.com", "parola": "parola123"},
        )
        assert response.status_code == 401

    def test_login_email_matching_is_case_insensitive(self, client):
        """The login endpoint lowercases the email before lookup."""
        client.post(
            "/inregistrare",
            json={"nume": "Ion", "email": "ion@example.com", "parola": "parola123"},
        )
        response = client.post(
            "/autentificare",
            json={"email": "ION@EXAMPLE.COM", "parola": "parola123"},
        )
        assert response.status_code == 200

    def test_access_protected_endpoint_without_token_fails(self, client):
        """Missing Authorization header returns 401 (HTTPBearer behaviour)."""
        response = client.get("/utilizatori/eu")
        assert response.status_code == 401

    def test_access_protected_endpoint_with_invalid_token_fails(self, client):
        response = client.get(
            "/utilizatori/eu",
            headers={"Authorization": "Bearer completely.invalid.token"},
        )
        assert response.status_code == 401

    def test_profile_endpoint_returns_current_user(self, client):
        token = register_and_login(client, "ion@example.com", "parola123", "Ion")
        response = client.get("/utilizatori/eu", headers=auth_headers(token))
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == "ion@example.com"
        assert body["nume"] == "Ion"
        # Hashed password must never be exposed
        assert "parola_hash" not in body


# ===========================================================================
# 2. Task CRUD tests
# ===========================================================================

class TestCreazaSarcina:
    """POST /sarcini"""

    def test_create_task_authenticated_returns_201(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": "Prima sarcina", "descriere": "O descriere"},
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["titlu"] == "Prima sarcina"
        assert body["descriere"] == "O descriere"
        assert body["finalizata"] == 0
        assert "id" in body
        assert "data_crearii" in body

    def test_create_task_without_description_uses_empty_string(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": "Fara descriere"},
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        assert response.json()["descriere"] == ""

    def test_create_task_default_priority_is_medie(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": "Sarcina"},
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        assert response.json()["prioritate"] == "medie"

    def test_create_task_with_explicit_priority(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": "Urgenta", "prioritate": "ridicata"},
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        assert response.json()["prioritate"] == "ridicata"

    def test_create_task_with_deadline(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": "Cu termen", "data_limita": "2026-12-31"},
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        assert response.json()["data_limita"] == "2026-12-31"

    def test_create_task_with_category(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": "Cu categorie", "categorie": "muncă"},
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        assert response.json()["categorie"] == "muncă"

    def test_create_task_without_auth_fails(self, client):
        response = client.post("/sarcini", json={"titlu": "Sarcina"})
        assert response.status_code == 401

    def test_create_task_associates_with_authenticated_user(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "Sarcina mea")
        assert "utilizator_id" in task
        assert isinstance(task["utilizator_id"], int)


class TestListaSarcini:
    """GET /sarcini"""

    def test_list_tasks_returns_only_own_tasks(self, client):
        token_a = register_and_login(client, "alice@example.com", "parola123", "Alice")
        token_b = register_and_login(client, "bob@example.com", "parola123", "Bob")

        create_task(client, token_a, "Sarcina Alice 1")
        create_task(client, token_a, "Sarcina Alice 2")
        create_task(client, token_b, "Sarcina Bob")

        response = client.get("/sarcini", headers=auth_headers(token_a))
        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 2
        assert all("Alice" in t["titlu"] for t in tasks)

    def test_list_tasks_empty_when_no_tasks_created(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.get("/sarcini", headers=auth_headers(token))
        assert response.status_code == 200
        assert response.json() == []

    def test_list_tasks_ordered_newest_first_by_default(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        create_task(client, token, "First")
        create_task(client, token, "Second")
        create_task(client, token, "Third")

        tasks = client.get("/sarcini", headers=auth_headers(token)).json()
        ids = [t["id"] for t in tasks]
        assert ids == sorted(ids, reverse=True)

    def test_list_tasks_filter_only_incomplete(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "Sa finalizez")

        # Toggle to complete (first call: 0 -> 1)
        client.patch(f"/sarcini/{task['id']}/finalizeaza", headers=auth_headers(token))
        create_task(client, token, "Inca nefinalizata")

        response = client.get("/sarcini?doar_nefinalizate=true", headers=auth_headers(token))
        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 1
        assert tasks[0]["titlu"] == "Inca nefinalizata"

    def test_list_tasks_without_auth_fails(self, client):
        response = client.get("/sarcini")
        assert response.status_code == 401


class TestObtineSarcina:
    """GET /sarcini/{id}"""

    def test_get_single_task_returns_correct_data(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        created = create_task(client, token, "Detalii sarcina", "Descriere detaliata")

        response = client.get(f"/sarcini/{created['id']}", headers=auth_headers(token))
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == created["id"]
        assert body["titlu"] == "Detalii sarcina"
        assert body["descriere"] == "Descriere detaliata"

    def test_get_nonexistent_task_returns_404(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.get("/sarcini/99999", headers=auth_headers(token))
        assert response.status_code == 404

    def test_get_another_users_task_returns_404(self, client):
        """A user must not be able to read a task that belongs to someone else."""
        token_a = register_and_login(client, "alice@example.com", "parola123", "Alice")
        token_b = register_and_login(client, "bob@example.com", "parola123", "Bob")

        task = create_task(client, token_a, "Sarcina privata a lui Alice")

        response = client.get(f"/sarcini/{task['id']}", headers=auth_headers(token_b))
        assert response.status_code == 404

    def test_get_task_without_auth_fails(self, client):
        response = client.get("/sarcini/1")
        assert response.status_code == 401


class TestActualizeazaSarcina:
    """PUT /sarcini/{id}"""

    def test_update_task_title(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "Titlu vechi")

        response = client.put(
            f"/sarcini/{task['id']}",
            json={"titlu": "Titlu nou"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["titlu"] == "Titlu nou"

    def test_update_task_description(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "Sarcina", "Descriere veche")

        response = client.put(
            f"/sarcini/{task['id']}",
            json={"descriere": "Descriere noua"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["descriere"] == "Descriere noua"

    def test_update_task_completion_flag_via_put(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "Sarcina")

        response = client.put(
            f"/sarcini/{task['id']}",
            json={"finalizata": True},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["finalizata"] == 1

    def test_update_task_priority(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "Sarcina")

        response = client.put(
            f"/sarcini/{task['id']}",
            json={"prioritate": "ridicata"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["prioritate"] == "ridicata"

    def test_update_preserves_unchanged_fields(self, client):
        """Sending only titlu must not wipe the existing descriere."""
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "Titlu", "Descriere importanta")

        response = client.put(
            f"/sarcini/{task['id']}",
            json={"titlu": "Titlu nou"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["descriere"] == "Descriere importanta"

    def test_update_nonexistent_task_returns_404(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.put(
            "/sarcini/99999",
            json={"titlu": "Nu exista"},
            headers=auth_headers(token),
        )
        assert response.status_code == 404

    def test_update_another_users_task_returns_404(self, client):
        token_a = register_and_login(client, "alice@example.com", "parola123", "Alice")
        token_b = register_and_login(client, "bob@example.com", "parola123", "Bob")

        task = create_task(client, token_a, "Sarcina lui Alice")

        response = client.put(
            f"/sarcini/{task['id']}",
            json={"titlu": "Bob modifica"},
            headers=auth_headers(token_b),
        )
        assert response.status_code == 404

    def test_update_task_without_auth_fails(self, client):
        response = client.put("/sarcini/1", json={"titlu": "Hacked"})
        assert response.status_code == 401


class TestFinalizeazaSarcina:
    """PATCH /sarcini/{id}/finalizeaza — toggles completion state"""

    def test_toggle_incomplete_task_to_complete(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "De finalizat")

        assert task["finalizata"] == 0

        response = client.patch(
            f"/sarcini/{task['id']}/finalizeaza",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["finalizata"] == 1

    def test_toggle_complete_task_back_to_incomplete(self, client):
        """A second call on an already-complete task must toggle it back to 0."""
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "De finalizat si anulat")

        # First toggle: 0 -> 1
        client.patch(f"/sarcini/{task['id']}/finalizeaza", headers=auth_headers(token))
        # Second toggle: 1 -> 0
        response = client.patch(
            f"/sarcini/{task['id']}/finalizeaza",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["finalizata"] == 0

    def test_finalize_nonexistent_task_returns_404(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.patch("/sarcini/99999/finalizeaza", headers=auth_headers(token))
        assert response.status_code == 404

    def test_finalize_another_users_task_returns_404(self, client):
        token_a = register_and_login(client, "alice@example.com", "parola123", "Alice")
        token_b = register_and_login(client, "bob@example.com", "parola123", "Bob")

        task = create_task(client, token_a, "Sarcina lui Alice")

        response = client.patch(
            f"/sarcini/{task['id']}/finalizeaza",
            headers=auth_headers(token_b),
        )
        assert response.status_code == 404

    def test_finalize_persists_in_subsequent_get(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "Persistent finalizare")

        client.patch(f"/sarcini/{task['id']}/finalizeaza", headers=auth_headers(token))

        fetched = client.get(f"/sarcini/{task['id']}", headers=auth_headers(token)).json()
        assert fetched["finalizata"] == 1

    def test_finalize_task_without_auth_fails(self, client):
        response = client.patch("/sarcini/1/finalizeaza")
        assert response.status_code == 401


class TestStergeSarcina:
    """DELETE /sarcini/{id}"""

    def test_delete_task_returns_success_message(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "De sters")

        response = client.delete(f"/sarcini/{task['id']}", headers=auth_headers(token))
        assert response.status_code == 200
        assert "ștearsă" in response.json()["mesaj"]

    def test_deleted_task_is_no_longer_retrievable(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "De sters")

        client.delete(f"/sarcini/{task['id']}", headers=auth_headers(token))

        response = client.get(f"/sarcini/{task['id']}", headers=auth_headers(token))
        assert response.status_code == 404

    def test_deleted_task_removed_from_list(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "De sters")

        client.delete(f"/sarcini/{task['id']}", headers=auth_headers(token))

        tasks = client.get("/sarcini", headers=auth_headers(token)).json()
        assert all(t["id"] != task["id"] for t in tasks)

    def test_delete_nonexistent_task_returns_404(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.delete("/sarcini/99999", headers=auth_headers(token))
        assert response.status_code == 404

    def test_delete_another_users_task_returns_404(self, client):
        token_a = register_and_login(client, "alice@example.com", "parola123", "Alice")
        token_b = register_and_login(client, "bob@example.com", "parola123", "Bob")

        task = create_task(client, token_a, "Sarcina lui Alice")

        response = client.delete(f"/sarcini/{task['id']}", headers=auth_headers(token_b))
        assert response.status_code == 404

    def test_delete_task_without_auth_fails(self, client):
        response = client.delete("/sarcini/1")
        assert response.status_code == 401


# ===========================================================================
# 3. Statistics endpoint tests
# ===========================================================================

class TestStatisticiSarcini:
    """GET /sarcini/statistici"""

    def test_statistics_returns_zeros_for_new_user(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.get("/sarcini/statistici", headers=auth_headers(token))
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["finalizate"] == 0
        assert body["nefinalizate"] == 0

    def test_statistics_counts_all_own_tasks(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        create_task(client, token, "T1")
        create_task(client, token, "T2")
        create_task(client, token, "T3")

        body = client.get("/sarcini/statistici", headers=auth_headers(token)).json()
        assert body["total"] == 3
        assert body["nefinalizate"] == 3
        assert body["finalizate"] == 0

    def test_statistics_counts_completed_tasks(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        t1 = create_task(client, token, "T1")
        create_task(client, token, "T2")

        # Toggle T1 to complete
        client.patch(f"/sarcini/{t1['id']}/finalizeaza", headers=auth_headers(token))

        body = client.get("/sarcini/statistici", headers=auth_headers(token)).json()
        assert body["total"] == 2
        assert body["finalizate"] == 1
        assert body["nefinalizate"] == 1

    def test_statistics_counts_overdue_tasks(self, client):
        """A task with a past data_limita that is not finalizata counts as depasite."""
        token = register_and_login(client, "user@example.com", "parola123")
        # Create a task with a deadline in the past
        client.post(
            "/sarcini",
            json={"titlu": "Intarziata", "data_limita": "2020-01-01"},
            headers=auth_headers(token),
        )
        create_task(client, token, "Fara termen")

        body = client.get("/sarcini/statistici", headers=auth_headers(token)).json()
        assert body["depasite"] == 1

    def test_statistics_isolates_per_user(self, client):
        """Statistics must reflect only the authenticated user's tasks."""
        token_a = register_and_login(client, "alice@example.com", "parola123", "Alice")
        token_b = register_and_login(client, "bob@example.com", "parola123", "Bob")

        create_task(client, token_a, "A1")
        create_task(client, token_a, "A2")
        create_task(client, token_b, "B1")

        body = client.get("/sarcini/statistici", headers=auth_headers(token_a)).json()
        assert body["total"] == 2

    def test_statistics_breakdown_by_priority(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        client.post("/sarcini", json={"titlu": "Low", "prioritate": "scazuta"}, headers=auth_headers(token))
        client.post("/sarcini", json={"titlu": "Med"}, headers=auth_headers(token))
        client.post("/sarcini", json={"titlu": "High", "prioritate": "ridicata"}, headers=auth_headers(token))

        body = client.get("/sarcini/statistici", headers=auth_headers(token)).json()
        dp = body["dupa_prioritate"]
        assert dp["scazuta"] == 1
        assert dp["medie"] == 1
        assert dp["ridicata"] == 1

    def test_statistics_without_auth_fails(self, client):
        response = client.get("/sarcini/statistici")
        assert response.status_code == 401


# ===========================================================================
# 4. Validation tests
# ===========================================================================

class TestValidareSarcina:
    """Input validation on the task endpoints."""

    def test_create_task_with_empty_title_fails(self, client):
        """titlu min_length=1, so an empty string must be rejected."""
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": ""},
            headers=auth_headers(token),
        )
        assert response.status_code == 422

    def test_create_task_with_title_too_long_fails(self, client):
        """titlu max_length=200."""
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": "x" * 201},
            headers=auth_headers(token),
        )
        assert response.status_code == 422

    def test_create_task_with_title_at_max_length_succeeds(self, client):
        """Exactly 200 characters must be accepted."""
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": "a" * 200},
            headers=auth_headers(token),
        )
        assert response.status_code == 201

    def test_create_task_with_description_too_long_fails(self, client):
        """descriere max_length=2000."""
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": "Valid", "descriere": "d" * 2001},
            headers=auth_headers(token),
        )
        assert response.status_code == 422

    def test_create_task_without_title_fails(self, client):
        """titlu is required (no default value)."""
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"descriere": "Fara titlu"},
            headers=auth_headers(token),
        )
        assert response.status_code == 422

    def test_create_task_with_invalid_priority_fails(self, client):
        """Only 'scazuta', 'medie', 'ridicata' are valid priority values."""
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": "Sarcina", "prioritate": "ultra"},
            headers=auth_headers(token),
        )
        assert response.status_code == 422

    def test_create_task_with_invalid_deadline_format_fails(self, client):
        """data_limita must match ISO 8601 format."""
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": "Sarcina", "data_limita": "31/12/2026"},
            headers=auth_headers(token),
        )
        assert response.status_code == 422

    def test_create_task_with_category_too_long_fails(self, client):
        """categorie max_length=50."""
        token = register_and_login(client, "user@example.com", "parola123")
        response = client.post(
            "/sarcini",
            json={"titlu": "Sarcina", "categorie": "c" * 51},
            headers=auth_headers(token),
        )
        assert response.status_code == 422

    def test_update_task_with_empty_title_fails(self, client):
        """titlu min_length=1 also applies on update."""
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "Titlu valid")

        response = client.put(
            f"/sarcini/{task['id']}",
            json={"titlu": ""},
            headers=auth_headers(token),
        )
        assert response.status_code == 422

    def test_update_task_with_title_too_long_fails(self, client):
        token = register_and_login(client, "user@example.com", "parola123")
        task = create_task(client, token, "Titlu valid")

        response = client.put(
            f"/sarcini/{task['id']}",
            json={"titlu": "x" * 201},
            headers=auth_headers(token),
        )
        assert response.status_code == 422


class TestValidareUtilizator:
    """Input validation on the auth endpoints."""

    def test_register_with_short_password_fails(self, client):
        """parola min_length=6."""
        response = client.post(
            "/inregistrare",
            json={"nume": "User", "email": "user@example.com", "parola": "abc"},
        )
        assert response.status_code == 422

    def test_register_with_password_of_five_chars_fails(self, client):
        response = client.post(
            "/inregistrare",
            json={"nume": "User", "email": "user@example.com", "parola": "abcde"},
        )
        assert response.status_code == 422

    def test_register_with_invalid_email_no_at_symbol_fails(self, client):
        response = client.post(
            "/inregistrare",
            json={"nume": "User", "email": "userexample.com", "parola": "parola123"},
        )
        assert response.status_code == 422

    def test_register_with_invalid_email_no_domain_fails(self, client):
        response = client.post(
            "/inregistrare",
            json={"nume": "User", "email": "user@", "parola": "parola123"},
        )
        assert response.status_code == 422

    def test_register_with_name_too_long_fails(self, client):
        """nume max_length=100."""
        response = client.post(
            "/inregistrare",
            json={"nume": "N" * 101, "email": "user@example.com", "parola": "parola123"},
        )
        assert response.status_code == 422

    def test_register_email_is_stored_in_lowercase(self, client):
        """The email validator normalises to lowercase before storage."""
        client.post(
            "/inregistrare",
            json={"nume": "User", "email": "User@Example.COM", "parola": "parola123"},
        )
        response = client.post(
            "/autentificare",
            json={"email": "user@example.com", "parola": "parola123"},
        )
        assert response.status_code == 200


# ===========================================================================
# 5. Health check
# ===========================================================================

class TestHealthCheck:
    def test_healthz_returns_ok(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}