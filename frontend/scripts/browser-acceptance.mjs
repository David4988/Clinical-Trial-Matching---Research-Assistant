/**
 * Drives the demo journey in a real Chrome and asserts what a judge will see.
 *
 * This exists because the checks that pass without a browser — pytest, tsc,
 * vite build, server-rendering a component — all passed while the Monitoring
 * tab was blank. A render crash unmounts React in the browser and nowhere
 * else, and a dead click handler is invisible to every one of them.
 *
 * Needs both servers up and an empty store:
 *   rm -f backend/data/store.json backend/data/monitoring.json
 *   cd backend && RISK_PROVIDER=synthetic_ml .venv/bin/python -m uvicorn app.main:app --port 8000
 *   cd frontend && npm run dev
 *   npm run acceptance:browser
 */

import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const APP = process.env.APP_URL ?? "http://localhost:5173/";
const CHROME =
  process.env.CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9444;

const chrome = spawn(
  CHROME,
  [
    "--headless=new",
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${mkdtempSync(join(tmpdir(), "acceptance-"))}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ],
  { stdio: "ignore" },
);

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

let target = null;
for (let i = 0; i < 60 && !target; i++) {
  try {
    const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
    target = list.find((t) => t.type === "page");
  } catch {}
  if (!target) await wait(250);
}
if (!target) {
  console.error("Chrome never exposed a debugging target");
  process.exit(1);
}

const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res, rej) => {
  ws.addEventListener("open", res, { once: true });
  ws.addEventListener("error", rej, { once: true });
});

let id = 1;
const pending = new Map();
const crashes = [];
ws.addEventListener("message", (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) {
    const { res, rej } = pending.get(d.id);
    pending.delete(d.id);
    d.error ? rej(new Error(JSON.stringify(d.error))) : res(d.result);
  } else if (d.method === "Runtime.exceptionThrown") {
    crashes.push(
      d.params.exceptionDetails.exception?.description ??
        d.params.exceptionDetails.text,
    );
  }
});
const send = (method, params = {}) =>
  new Promise((res, rej) => {
    pending.set(id, { res, rej });
    ws.send(JSON.stringify({ id: id++, method, params }));
  });

await send("Runtime.enable");
await send("Page.enable");

const evaluate = async (expression) => {
  const r = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (r.exceptionDetails) {
    throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
  }
  return r.result.value;
};
const text = () => evaluate("document.body.innerText");
const click = async (label) => {
  const ok = await evaluate(`(() => {
    const el = [...document.querySelectorAll('button')]
      .find(n => (n.textContent || "").toLowerCase().includes(${JSON.stringify(label.toLowerCase())}));
    if (!el || el.disabled) return false;
    el.click();
    return true;
  })()`);
  if (!ok) throw new Error(`no enabled button matching ${JSON.stringify(label)}`);
  await wait(900);
};
const fill = async (elementId, value) => {
  const ok = await evaluate(`(() => {
    const el = document.getElementById(${JSON.stringify(elementId)});
    if (!el) return false;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")
      .set.call(el, ${JSON.stringify(value)});
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  })()`);
  if (!ok) throw new Error(`no field #${elementId}`);
};

const results = [];
const check = (label, pass, detail = "") => {
  results.push({ label, pass, detail });
  console.log(`  ${pass ? "ok  " : "FAIL"} ${label}${detail ? " — " + detail : ""}`);
};

try {
  await send("Page.navigate", { url: APP });
  await wait(1800);

  await click("Run demo candidate");
  await wait(1600);
  check("sample screening returns REVIEW_REQUIRED", /REVIEW REQUIRED/i.test(await text()));

  await click("Approve for Phase 2");
  await fill("reviewer", "Dr Reviewer");
  await fill("review-note", "Approving for phase 2.");
  await click("Confirm decision");
  await wait(2000);

  const enrolled = (await text()).includes("Record administration");
  check("approval enrols the participant", enrolled,
    enrolled ? "" : "clear backend/data/*.json — an active treatment already exists");
  if (!enrolled) throw new Error("enrolment blocked");

  await fill("dose-by", "Nurse A");
  await click("Record administration");
  await wait(1800);
  await click("Open monitoring");
  await wait(2200);

  const monitoring = await text();
  check("monitoring renders (not blank)", monitoring.length > 200, `${monitoring.length} chars`);
  check("participant carried across the phase boundary", monitoring.includes("P-1042"));
  check("model badge reports live inference",
    /synthetic_ml/.test(monitoring) && /synthetic_if_v1/.test(monitoring) && /LIVE/.test(monitoring));
  check("first load offers the no-cycle-yet state",
    /AWAITING FIRST OBSERVATIONS/i.test(monitoring));

  // Reload first: that drops the Phase 1 handoff, so the participant is reached
  // with no focus and no cycle — the state a judge lands in by opening
  // Monitoring directly, and the one where Advance used to do nothing at all.
  await send("Page.navigate", { url: APP });
  await wait(2000);
  await click("Monitoring");
  await wait(1500);
  const selected = await evaluate(`(() => {
    const el = [...document.querySelectorAll('button')].find(n => (n.textContent||"").includes("P-1042"));
    if (!el) return false;
    el.click();
    return true;
  })()`);
  check("board lists the enrolled participant", selected);
  await wait(1800);
  await click("Advance monitoring");
  await wait(3000);
  check("advance works for a participant selected from the board",
    !/AWAITING FIRST OBSERVATIONS/i.test(await text()));

  for (let i = 0; i < 4; i++) {
    try {
      await click("Advance monitoring");
      await wait(3000);
    } catch {
      break;
    }
  }

  const advanced = await text();
  check("trajectory reaches RED on live inference", /\bRED\b/.test(advanced));
  check("protocol actions are shown",
    /urgent escalation|notify clinician|increase monitoring/i.test(advanced));

  await click("Hold treatment");
  await fill("investigator-name", "Dr Investigator");
  await fill("investigator-note", "Holding the course.");
  await click("Record decision");
  await wait(2500);
  const reviewed = await text();
  check("investigator review records", /Recorded decisions/i.test(reviewed));
  check("hold puts the treatment on hold", /ON_HOLD/i.test(reviewed));

  check("no uncaught exceptions", crashes.length === 0, crashes.join(" | "));
} catch (error) {
  check("journey completed", false, error.message);
} finally {
  ws.close();
  chrome.kill();
}

const failed = results.filter((r) => !r.pass);
console.log(
  failed.length
    ? `\n${failed.length} of ${results.length} checks failed`
    : `\nall ${results.length} browser checks passed`,
);
process.exit(failed.length ? 1 : 0);
