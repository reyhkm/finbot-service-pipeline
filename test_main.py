from fastapi.testclient import TestClient
from main import app, pastikan_saham_indo

client = TestClient(app)

def test_health_check_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert "Running" in response.json()["status"]

def test_pastikan_saham_indo():
    assert pastikan_saham_indo("BBCA") == "BBCA.JK"
    assert pastikan_saham_indo("IHSG") == "^JKSE"
    assert pastikan_saham_indo("TLKM.JK") == "TLKM.JK"
