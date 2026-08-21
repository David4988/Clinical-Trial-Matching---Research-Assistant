import requests
import json
import time

BASE_URL = "http://localhost:8000/monitoring"

# 1. Reset P-1042 by hitting something? We can't reset, but we can generate a new patient or just hit advance if they are already enrolled.
# Let's see the patient's state first.
res = requests.get(f"{BASE_URL}/patients/P-1042/state?trial_id=CT-001")
if res.status_code == 200:
    state = res.json()
    print("Patient state history:", state.get("history_duration_minutes"))

# 2. Let's see the latest cycle
res = requests.get(f"{BASE_URL}/patients/P-1042/cycle")
if res.status_code == 200:
    cycle = res.json()
    ew = cycle.get("early_warning", {})
    print("Early Warning:", ew)
