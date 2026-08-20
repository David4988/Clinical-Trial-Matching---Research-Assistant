import sys
from pathlib import Path
from datetime import datetime, timezone
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.trajectory_replay import load_trajectory, replay, build_app, DEFAULT_PATIENT
from fastapi.testclient import TestClient
import tempfile

def main():
    trajectory = load_trajectory()
    with tempfile.TemporaryDirectory() as tmp:
        app = build_app(Path(tmp), "synthetic_ml")
        client = TestClient(app)
        
        # We modify replay to just run it and we will pull the cycles manually
        windows = replay(client, trajectory, first=96, last=111, verify_consistency=False)
        change_point = trajectory["change_point_window"]
        
        print(f"Change point: {change_point}")
        
        # Get timeline or cycles
        # Because replay() creates cycles, let's just use the app's repository
        repo = app.state.monitoring.repository
        
        ew_flagged_first = None
        if_flagged_first = None
        
        for w in windows:
            cycle = repo.latest_cycle(DEFAULT_PATIENT) # Wait, it only gets latest.
            pass
            
        # Instead, let's just get all cycles
        cycles = repo._cycles[DEFAULT_PATIENT]
        for c in cycles:
            w_idx = None
            for w in trajectory["windows"]:
                if w["observed"]["heart_rate"] == c.state.recent_observations[-1].value and c.state.recent_observations[-1].measurement_type.value == "HEART_RATE":
                    w_idx = w["window_index"]
                    break
                    
            if_risk = c.effective_risk.level.value
            ew_risk = None
            if c.early_warning and c.early_warning.predicted_deterioration:
                ew_risk = "ELEVATED"
                
            print(f"Window {w_idx} | IF: {if_risk} | EW: {ew_risk} | Score: {c.early_warning.score if c.early_warning else None}")
            
            if if_risk == "RED" and if_flagged_first is None:
                if_flagged_first = w_idx
            if ew_risk == "ELEVATED" and ew_flagged_first is None:
                ew_flagged_first = w_idx
                
        print(f"IF flagged at: {if_flagged_first}")
        print(f"EW flagged at: {ew_flagged_first}")
        if ew_flagged_first and if_flagged_first:
            lead = (if_flagged_first - ew_flagged_first) * 5
            print(f"Lead time: {lead} minutes")

if __name__ == "__main__":
    main()
