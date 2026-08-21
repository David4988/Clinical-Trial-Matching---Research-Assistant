import requests

BASE_URL = "http://localhost:8000/monitoring"

res = requests.post(f"{BASE_URL}/patients/P-1042/advance", json={
    "trial_id": "CT-001",
    "window_index": 2,
    "windows": 5,
    "hours": 8.0,
    "interval_minutes": 15
})

if res.status_code == 200:
    cycle = res.json()
    ew = cycle.get("early_warning", {})
    print("Early Warning after 3rd window:", ew)
else:
    print(res.status_code, res.text)
