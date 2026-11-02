import os, sys, tempfile, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["ALLOW_PRIVATE"] = "1"
os.environ["DATA_DIR"] = tempfile.mkdtemp()
from fastapi.testclient import TestClient
from fixtures.pages import Server

@pytest.fixture(scope="session")
def srv():
    s = Server(); yield s; s.stop()

@pytest.fixture(scope="session")
def client():
    from app.main import app
    return TestClient(app)

def make_user(client, email):
    t = client.post("/api/v1/auth/register", json={"email": email, "password": "password123"}).json()["token"]
    return {"Authorization": f"Bearer {t}"}
