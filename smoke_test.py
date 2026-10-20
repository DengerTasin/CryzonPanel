"""Render every GET route with the Flask test client to catch template errors."""
import os
os.environ["CRYZON_DEMO"] = "1"

from ccp import create_app

app = create_app()
app.config["TESTING"] = True

PUBLIC = ["/", "/login", "/register"]
AUTH = [
    "/dashboard", "/profile", "/ports", "/tickets", "/notifications",
]
ADMIN = [
    "/admin/", "/admin/vps", "/admin/users", "/admin/roles",
    "/admin/nodes", "/admin/settings", "/admin/logs",
]

fails = []

with app.test_client() as c:
    for url in PUBLIC:
        r = c.get(url)
        status = r.status_code
        flag = "OK " if status in (200, 302) else "FAIL"
        if status not in (200, 302):
            fails.append((url, status, r.data[:400]))
        print(f"[{flag}] {status}  {url}")

    # login as admin
    r = c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False)
    print(f"[login] {r.status_code} -> {r.headers.get('Location')}")

    for url in AUTH + ADMIN:
        r = c.get(url)
        status = r.status_code
        flag = "OK " if status in (200, 302) else "FAIL"
        if status not in (200, 302):
            fails.append((url, status, r.data[:600]))
        print(f"[{flag}] {status}  {url}")

print("\n=== RESULT ===")
if fails:
    print(f"{len(fails)} FAILURES")
    for url, status, body in fails:
        print(f"\n--- {url} ({status}) ---")
        print(body.decode("utf-8", "replace"))
else:
    print("ALL ROUTES RENDERED OK")
