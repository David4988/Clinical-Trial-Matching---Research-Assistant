import type {
  ApiError,
  Patient,
  ReviewDecision,
  ScreeningResult,
  Trial,
} from "../types/canonical";

const BASE = "/api";

/** Thrown for every non-2xx response, always carrying the structured body. */
export class ScreeningApiError extends Error {
  constructor(public readonly error: ApiError) {
    super(error.message);
    this.name = "ScreeningApiError";
  }
}

async function unwrap(response: Response): Promise<ScreeningResult> {
  if (response.ok) return response.json();

  let error: ApiError = {
    code: `HTTP_${response.status}`,
    message: "The server returned an unexpected response.",
    details: [],
  };
  try {
    const body = await response.json();
    if (body?.error) error = body.error;
  } catch {
    // Body was not JSON — keep the generic error above.
  }
  throw new ScreeningApiError(error);
}

export async function screenPdf(file: File): Promise<ScreeningResult> {
  const form = new FormData();
  form.append("file", file);
  return unwrap(await fetch(`${BASE}/screen/pdf`, { method: "POST", body: form }));
}

export async function screenCanonical(
  patient: Patient,
  trial: Trial,
): Promise<ScreeningResult> {
  return unwrap(
    await fetch(`${BASE}/screen`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patient, trial }),
    }),
  );
}

export async function listResults(): Promise<ScreeningResult[]> {
  const response = await fetch(`${BASE}/results`);
  if (!response.ok) return [];
  return response.json();
}

/**
 * Record a human decision about a screening.
 *
 * Returns the same result with `review` populated. The deterministic fields
 * come back unchanged — the backend refuses to let a review edit a verdict.
 */
export async function recordReview(
  resultId: string,
  decision: ReviewDecision,
  reviewer: string,
  note: string,
): Promise<ScreeningResult> {
  return unwrap(
    await fetch(`${BASE}/results/${encodeURIComponent(resultId)}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reviewer, note }),
    }),
  );
}
