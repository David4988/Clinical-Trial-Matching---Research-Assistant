/**
 * Regression test for the Work Queue draft/approval render bug: `onInvestigate`
 * and `onApprove` (`components/queue/WorkQueueApp.tsx`) used to call
 * `loadItem(id)` right after `setProposal(freshProposal)`. `loadItem`'s own
 * `setProposal(null)` ran in the SAME React batch (no `await` separates the
 * two calls — `investigate()`'s promise had already resolved, so the rest of
 * `onInvestigate` and all of `loadItem` up to its own first `await` run
 * synchronously). The fresh proposal was overwritten before it ever painted:
 * a researcher clicking "Draft a request" saw the button silently revert,
 * with no subject, body, or provenance ever shown — indistinguishable from
 * "nothing happened". Same bug, same fix, for `onApprove`.
 *
 * This exists because that class of bug is invisible to `tsc`, `vite build`,
 * and `render-smoke.mjs` (server-side rendering can't reproduce a
 * multi-step client-side state race) — only a real browser catches it, same
 * reasoning as `browser-acceptance.mjs`'s own header comment.
 *
 * Forces the In-App channel before approving, so this can never place a
 * real external send regardless of which credentials are configured in the
 * environment it runs in.
 *
 * Needs both servers up and an obligation already detected:
 *   cd backend && PERSISTENCE=json DATA_DIR=/tmp/wq-accept-data \
 *     .venv/bin/python -m uvicorn app.main:app --port 8000 &
 *   curl -s -X POST http://127.0.0.1:8000/screen -H "Content-Type: application/json" \
 *     -d "{\"patient\": $(cat fixtures/patient_incomplete.json), \"trial\": $(cat fixtures/trial_demo.json)}" >/dev/null
 *   cd frontend && npm run dev
 *   npm run acceptance:work-queue
 */

import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const APP = process.env.APP_URL ?? "http://localhost:5173/";
const CHROME =
  process.env.CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9447;

const chrome = spawn(
  CHROME,
  [
    "--headless=new",
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${mkdtempSync(join(tmpdir(), "wq-acceptance-"))}`,
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
  await wait(1000);
};
const fillByLabel = async (labelSubstr, value) => {
  const ok = await evaluate(`(() => {
    const label = [...document.querySelectorAll('label')]
      .find(l => (l.textContent||"").toLowerCase().includes(${JSON.stringify(labelSubstr.toLowerCase())}));
    const input = label ? label.querySelector('input') : null;
    if (!input) return false;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  })()`);
  if (!ok) throw new Error(`no input under label ${JSON.stringify(labelSubstr)}`);
};
/** Guarantees the send goes through the In-App provider, never Gmail/WhatsApp,
 * no matter what credentials the running backend has loaded. */
const forceInAppChannel = async () => {
  const ok = await evaluate(`(() => {
    const select = [...document.querySelectorAll('select')][0];
    if (!select) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
    setter.call(select, "IN_APP");
    select.dispatchEvent(new Event("change", { bubbles: true }));
    return select.value === "IN_APP";
  })()`);
  if (!ok) throw new Error("could not force the In-App channel");
};

const results = [];
const check = (label, pass, detail = "") => {
  results.push({ label, pass, detail });
  console.log(`  ${pass ? "ok  " : "FAIL"} ${label}${detail ? " — " + detail : ""}`);
};

try {
  await send("Page.navigate", { url: APP });
  await wait(1500);

  await click("Work Queue");
  const queueText = await text();
  check("an obligation is present to open (seed it first — see header comment)",
    /P-\d{4}/.test(queueText), queueText.slice(0, 120));

  const opened = await evaluate(`(() => {
    const el = [...document.querySelectorAll('button')].find(n => /P-\\d{4}/.test(n.textContent||""));
    if (!el) return false;
    el.click();
    return true;
  })()`);
  check("obligation row opens", opened);
  await wait(1000);

  check("shows 'Draft a request' before investigating", (await text()).includes("Draft a request"));

  await click("Draft a request");
  await wait(2000);
  const afterDraft = await text();

  check("draft subject/body render after investigating",
    /Screening for .* cannot complete/.test(afterDraft));
  check("provenance badge renders", /TEMPLATE|LOCAL|HOSTED/.test(afterDraft));
  check("approve form (reviewer/note) renders", afterDraft.includes("Approve") && afterDraft.includes("Reviewer"));

  await forceInAppChannel();
  await fillByLabel("Reviewer", "Dr. Acceptance Test");
  await fillByLabel("Note (required)", "Automated acceptance run — In-App channel forced.");
  await click("Approve & send");
  await wait(2000);
  const afterApprove = await text();

  check("post-approval execution status renders (not silently reverted)",
    /Proposal PA-[A-Za-z0-9]+: EXECUTED/.test(afterApprove));
  check("delivery went through the in-app provider, not an external one",
    /via in-app/i.test(afterApprove));

  check("no uncaught runtime exceptions", crashes.length === 0, crashes.join(" | "));
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
