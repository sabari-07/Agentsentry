import httpx

API = "https://6klp6vbzza.execute-api.us-east-1.amazonaws.com"
data = httpx.get(f"{API}/api/incidents", timeout=30).json()
for i in data:
    if i["status"] in ("PR_OPEN", "DEPLOYING", "DIAGNOSING"):
        r = httpx.post(f"{API}/api/verification/{i['id']}", timeout=60)
        print("status_code:", r.status_code)
        print("body:", r.text[:500])
