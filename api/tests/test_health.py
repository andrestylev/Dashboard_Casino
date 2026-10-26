from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_db_check_reports_demo_data(monkeypatch):
    class Result:
        def __init__(self, row):
            self.row = row

        def scalar_one(self):
            return self.row

        def one(self):
            return self.row

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, statement):
            if "version()" in str(statement):
                return Result("PostgreSQL test")
            return Result((True, True))

    class Engine:
        def connect(self):
            return Connection()

    monkeypatch.setattr("app.main.engine", Engine())
    response = client.get("/api/db-check")

    assert response.status_code == 200
    assert response.json() == {
        "database": "ok",
        "version": "PostgreSQL test",
        "seed_loaded": True,
        "seed_note": "Player and bet records found.",
    }


def test_db_check_reports_missing_demo_data(monkeypatch):
    class Result:
        def scalar_one(self):
            return "PostgreSQL test"

        def one(self):
            return (False, False)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, _statement):
            return Result()

    class Engine:
        def connect(self):
            return Connection()

    monkeypatch.setattr("app.main.engine", Engine())
    response = client.get("/api/db-check")

    assert response.status_code == 200
    assert response.json()["seed_loaded"] is False
    assert response.json()["seed_note"] is None
