"""One-off: copy a developer's local JSON stores into PostgreSQL.

There is no production data to migrate (`backend/data/*.json` are
git-ignored, regenerated-by-running-the-app development artefacts — see
`docs/FINAL_IMPLEMENTATION_PLAN.md` §11.6), so this script exists for two
narrower reasons: a developer switching `PERSISTENCE` from `json` to
`postgres` mid-project keeps their local demo state, and the two repository
implementations can be diffed against each other on real data instead of only
synthetic fixtures.

Run:  python scripts/import_json_store.py [--data-dir PATH]

Requires `DATABASE_URL` (and, if different, `MIGRATION_DATABASE_URL`) to be
set, and the schema to already be migrated — run `alembic upgrade head`
first.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.engine import build_engine, database_url  # noqa: E402
from app.repository.json_monitoring import JsonMonitoringRepository  # noqa: E402
from app.repository.json_repo import JsonRepository  # noqa: E402
from app.repository.sql_monitoring import SqlMonitoringRepository  # noqa: E402
from app.repository.sql_repo import SqlRepository  # noqa: E402


def import_screening(json_repo: JsonRepository, sql_repo: SqlRepository) -> int:
    results = json_repo.list_screening_results()
    for result in results:
        sql_repo.save_screening_result(result)
    return len(results)


def import_monitoring(json_repo: JsonMonitoringRepository, sql_repo: SqlMonitoringRepository) -> dict[str, int]:
    counts = {"treatments": 0, "observations": 0, "adverse_events": 0, "cycles": 0, "notifications": 0}

    treatments = json_repo.list_treatments()
    for treatment in treatments:
        sql_repo.save_treatment(treatment)
    counts["treatments"] = len(treatments)

    # Observations and events are bucketed by patient_id in the JSON store;
    # walk every patient that has a treatment, which is every patient this
    # store has ever seen doses, vitals, or a cycle for.
    patient_ids = {t.patient_id for t in treatments}
    all_observations = []
    all_events = []
    for patient_id in patient_ids:
        all_observations.extend(json_repo.list_observations(patient_id))
        for event in json_repo.list_adverse_events(patient_id):
            sql_repo.save_adverse_event(event)
            counts["adverse_events"] += 1
        for cycle in json_repo.list_cycles(patient_id):
            sql_repo.save_cycle(cycle)
            counts["cycles"] += 1
        all_events.extend(json_repo.list_events(patient_id))

    if all_observations:
        sql_repo.save_observations(all_observations)
    counts["observations"] = len(all_observations)

    if all_events:
        sql_repo.append_events(all_events)

    notifications = json_repo.list_notifications()
    if notifications:
        sql_repo.save_notifications(notifications)
    counts["notifications"] = len(notifications)

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory holding store.json / monitoring.json (default: DATA_DIR or backend/data)",
    )
    args = parser.parse_args()

    if not database_url():
        print("DATABASE_URL is not set — nothing to import into.", file=sys.stderr)
        raise SystemExit(1)

    from app.repository.paths import data_dir

    base = args.data_dir or data_dir()
    json_repo = JsonRepository(base / "store.json")
    json_monitoring = JsonMonitoringRepository(base / "monitoring.json")

    engine = build_engine()
    sql_repo = SqlRepository(engine)
    sql_monitoring = SqlMonitoringRepository(engine)

    screened = import_screening(json_repo, sql_repo)
    monitoring_counts = import_monitoring(json_monitoring, sql_monitoring)

    print(f"Imported {screened} screening result(s).")
    for key, count in monitoring_counts.items():
        print(f"Imported {count} {key.replace('_', ' ')}.")


if __name__ == "__main__":
    main()
