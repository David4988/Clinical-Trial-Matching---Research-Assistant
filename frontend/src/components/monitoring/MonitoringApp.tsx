import { useCallback, useEffect, useState } from "react";
import { ScreeningApiError } from "../../api/client";
import {
  fetchLatestCycle,
  fetchOverview,
  fetchTimeline,
  seedDemo,
} from "../../api/monitoring";
import type { ApiError } from "../../types/canonical";
import type {
  MonitoringCycleResult,
  MonitoringEvent,
  TrialOverview,
} from "../../types/monitoring";
import { PatientMonitor } from "./PatientMonitor";
import { PatientTimeline } from "./PatientTimeline";
import { TrialOverviewView } from "./TrialOverview";

/**
 * Container for the Phase 2 views. Owns fetching and view state only — no
 * clinical logic lives here, and nothing is computed client-side: every level,
 * action and decision arrives already derived from the backend.
 */

const TRIAL_ID = "CT-001";

type View =
  | { kind: "overview" }
  | { kind: "patient"; patientId: string };

export function MonitoringApp() {
  const [view, setView] = useState<View>({ kind: "overview" });
  const [overview, setOverview] = useState<TrialOverview | null>(null);
  const [cycle, setCycle] = useState<MonitoringCycleResult | null>(null);
  const [timeline, setTimeline] = useState<MonitoringEvent[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const asApiError = (err: unknown): ApiError =>
    err instanceof ScreeningApiError
      ? err.error
      : {
          code: "NETWORK_ERROR",
          message: "Could not reach the monitoring service.",
          details: ["Confirm the backend is running on port 8000."],
        };

  const loadOverview = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setOverview(await fetchOverview(TRIAL_ID));
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }, []);

  const loadPatient = useCallback(async (patientId: string) => {
    setBusy(true);
    setError(null);
    try {
      const [nextCycle, events] = await Promise.all([
        fetchLatestCycle(patientId),
        fetchTimeline(patientId),
      ]);
      setCycle(nextCycle);
      setTimeline(events);
      setView({ kind: "patient", patientId });
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  async function onSeed() {
    setBusy(true);
    setError(null);
    try {
      await seedDemo(TRIAL_ID);
      setOverview(await fetchOverview(TRIAL_ID));
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Toolbar
        view={view}
        busy={busy}
        empty={(overview?.total_patients ?? 0) === 0}
        onBack={() => {
          setView({ kind: "overview" });
          void loadOverview();
        }}
        onRefresh={() =>
          view.kind === "overview"
            ? void loadOverview()
            : void loadPatient(view.patientId)
        }
        onSeed={onSeed}
      />

      {error && <ErrorNotice error={error} />}

      {busy && !overview && <Loading />}

      {view.kind === "overview"
        ? overview && (
            <TrialOverviewView overview={overview} onSelect={loadPatient} />
          )
        : cycle && (
            <div className="space-y-8">
              <PatientMonitor cycle={cycle} />
              <PatientTimeline events={timeline} />
            </div>
          )}
    </div>
  );
}

function Toolbar({
  view,
  busy,
  empty,
  onBack,
  onRefresh,
  onSeed,
}: {
  view: View;
  busy: boolean;
  empty: boolean;
  onBack: () => void;
  onRefresh: () => void;
  onSeed: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule pb-3">
      <div className="flex items-center gap-3">
        {view.kind === "patient" && (
          <button
            type="button"
            onClick={onBack}
            className="border border-rule-strong px-3 py-1.5 text-[12px] hover:border-ink"
          >
            ← All patients
          </button>
        )}
        <span className="eyebrow">
          {view.kind === "overview" ? "Trial overview" : view.patientId}
        </span>
      </div>

      <div className="flex items-center gap-2">
        {busy && <span className="text-[11px] text-ink-faint">working…</span>}
        <button
          type="button"
          onClick={onRefresh}
          disabled={busy}
          className="border border-rule-strong px-3 py-1.5 text-[12px] hover:border-ink disabled:opacity-40"
        >
          Refresh
        </button>
        {empty && view.kind === "overview" && (
          <button
            type="button"
            onClick={onSeed}
            disabled={busy}
            className="border border-ink bg-ink px-3 py-1.5 text-[12px] font-medium text-paper hover:bg-ink/90 disabled:opacity-40"
          >
            Load demo cohort
          </button>
        )}
      </div>
    </div>
  );
}

function Loading() {
  return (
    <div className="border border-dashed border-rule-strong bg-panel p-8 text-center">
      <div className="relative mx-auto mb-3 h-0.5 w-40 overflow-hidden bg-band">
        <div className="animate-sweep absolute inset-y-0 w-1/4 bg-ink" />
      </div>
      <div className="eyebrow">Loading monitoring data</div>
    </div>
  );
}

function ErrorNotice({ error }: { error: ApiError }) {
  return (
    <div className="border border-alert/35 bg-alert-wash p-4">
      <div className="text-[10px] font-semibold tracking-[0.12em] text-alert">
        {error.code}
      </div>
      <p className="mt-1 font-sans text-[14px] text-ink">{error.message}</p>
      {error.details.length > 0 && (
        <ul className="mt-2 space-y-1 font-sans text-[12px] text-ink-mid">
          {error.details.map((detail, index) => (
            <li key={index}>{detail}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
