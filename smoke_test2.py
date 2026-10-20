"""Create demo entities and render the dynamic detail routes."""
import os
os.environ["CRYZON_DEMO"] = "1"

from ccp import create_app, db

app = create_app()
app.config["TESTING"] = True

fails = []

with app.test_client() as c:
    c.post("/login", data={"username": "admin", "password": "admin123"})

    # Create a VPS as admin
    r = c.post("/vps/create", data={
        "os_type": "ubuntu-24.04", "ram": "4GB", "cpu": "2", "disk": "40GB",
    }, follow_redirects=False)
    print(f"[create vps] {r.status_code} -> {r.headers.get('Location')}")

    with app.app_context():
        v = db.query("SELECT * FROM vps ORDER BY id DESC LIMIT 1", one=True)
        vps_id = v["id"] if v else None
        print("vps_id =", vps_id)

    # Create a ticket
    r = c.post("/tickets/create", data={"subject": "Test ticket", "message": "Hello support"}, follow_redirects=False)
    print(f"[create ticket] {r.status_code} -> {r.headers.get('Location')}")
    with app.app_context():
        t = db.query("SELECT * FROM tickets ORDER BY id DESC LIMIT 1", one=True)
        tid = t["id"] if t else None
        print("tid =", tid)

    routes = []
    if vps_id:
        routes += [
            f"/vps/{vps_id}",
            f"/vps/{vps_id}/console",
            f"/vps/{vps_id}/files",
            f"/vps/{vps_id}/processes",
            f"/admin/vps/{vps_id}",
        ]
    if tid:
        routes.append(f"/tickets/{tid}")

    for url in routes:
        r = c.get(url)
        status = r.status_code
        flag = "OK " if status in (200, 302) else "FAIL"
        if status not in (200, 302):
            fails.append((url, status, r.data[:800]))
        print(f"[{flag}] {status}  {url}")

print("\n=== RESULT ===")
if fails:
    for url, status, body in fails:
        print(f"\n--- {url} ({status}) ---")
        print(body.decode("utf-8", "replace"))
else:
    print("ALL DYNAMIC ROUTES RENDERED OK")
