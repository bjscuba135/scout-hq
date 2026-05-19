import sys
sys.path.insert(0, '/app')
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
headers = {"Authorization": "Basic QmVuOjMyMTAxODE0NA==", "HX-Request": "true"}
task_id = "6057cdca-85bc-4e8b-8800-92f22c8175b3"

print("=== Test 1: JSON with list ===")
r = client.post(f"/tasks/{task_id}/entities/attach", headers=headers,
    json={"entity_names": ["Scouts"], "entity_types": {}})
print(r.status_code, r.text[:300])

print("\n=== Test 2: JSON with string ===")
r = client.post(f"/tasks/{task_id}/entities/attach", headers=headers,
    json={"entity_names": "Scouts", "entity_types": {}})
print(r.status_code, r.text[:300])

print("\n=== Test 3: empty body ===")
r = client.post(f"/tasks/{task_id}/entities/attach", headers=headers,
    json={})
print(r.status_code, r.text[:300])

print("\n=== Test 4: raw body log ===")
import asyncio
from app.routes.context import AttachEntities
try:
    m = AttachEntities(**{"entity_names": ["Scouts"], "entity_types": {}})
    print("Model ok:", m.entity_names, m.entity_types)
except Exception as e:
    print("Model error:", e)
