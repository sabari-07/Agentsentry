import httpx

API = "https://6klp6vbzza.execute-api.us-east-1.amazonaws.com"
data = httpx.get(f"{API}/api/incidents", timeout=30).json()
print("incident count:", len(data))
for i in data:
    print(f"\n{i['id']} | {i['status']} | {i['title']}")
    pr = i.get("pull_request")
    if pr:
        print("  PR number:", pr["number"])
        print("  PR url   :", pr["url"] or "(none - not created)")
        print("  branch   :", pr["branch"])
    audit = httpx.get(f"{API}/api/audit/{i['id']}", timeout=30).json()
    print("  audit    :", [(a["event_name"], a["read_only"]) for a in audit])
