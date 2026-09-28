"""Run the verification loop on any open incident (re-checks the live metric)."""
import httpx

API = "https://6klp6vbzza.execute-api.us-east-1.amazonaws.com"

for i in httpx.get(f"{API}/api/incidents", timeout=30).json():
    if i["status"] in ("PR_OPEN", "DEPLOYING", "DIAGNOSING"):
        r = httpx.post(f"{API}/api/verification/{i['id']}", timeout=60)
        print(f"{i['id']} -> HTTP {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            print("  status:", d["status"])
            v = d.get("verification") or {}
            print("  metric:", v.get("metric_name"), "observed:", v.get("observed_value"))
            print("  summary:", v.get("summary"))
