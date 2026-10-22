import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { Home, Network, Settings, List, Send, Sun, Moon } from "lucide-react";

const THEME_KEY = "bloodflow-theme";
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
function useTheme() {
  // null = follow the OS; "light"/"dark" = explicit choice, remembered locally.
  let [chosen, setChosen] = useState(() => {
      try {
        return localStorage.getItem(THEME_KEY);
      } catch {
        return null;
      }
    }),
    [systemDark, setSystemDark] = useState(darkQuery.matches);
  useEffect(() => {
    let onChange = (e) => setSystemDark(e.matches);
    darkQuery.addEventListener("change", onChange);
    return () => darkQuery.removeEventListener("change", onChange);
  }, []);
  useEffect(() => {
    if (chosen) document.documentElement.dataset.theme = chosen;
    else delete document.documentElement.dataset.theme;
  }, [chosen]);
  let theme = chosen || (systemDark ? "dark" : "light");
  function toggle() {
    let next = theme === "dark" ? "light" : "dark";
    setChosen(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {}
  }
  return [theme, toggle];
}
const names = {
    B1: "Saint-Antoine",
    B2: "Cabanel",
    H1: "Lariboisière",
    H2: "Pitié-Salpêtrière",
    H3: "Georges-Pompidou",
    H4: "Bichat",
  },
  groups = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"];
async function api(path, body) {
  let r = await fetch(
      "/ui/" + path,
      body
        ? {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }
        : {},
    ),
    d = await r.json();
  if (!r.ok)
    throw Error(typeof d.detail === "string" ? d.detail : "Invalid request");
  return d;
}
function Graph({ plan, group }) {
  let pos = {
    B1: [100, 100],
    B2: [100, 260],
    H1: [520, 50],
    H2: [520, 140],
    H3: [520, 230],
    H4: [520, 320],
  };
  return (
    <section className="panel" id="network">
      <div className="heading">
        <h2>Allocation network</h2>
        <span className="status">
          ● {plan?.solver_status || "Awaiting review"}
        </span>
      </div>
      <p className="caption">Schematic network · hypothetical transfers</p>
      <svg
        viewBox="0 0 750 390"
        role="img"
        aria-label="Blood bank to hospital allocation network"
      >
        <defs>
          <pattern
            id="dots"
            width="23"
            height="23"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="2" cy="2" r="1" style={{ fill: "var(--graph-dots)" }} />
          </pattern>
        </defs>
        <rect width="750" height="390" fill="url(#dots)" />
        {(plan?.graph.edges || [])
          .filter((e) => group === "all" || e.blood_type === group)
          .map((e, i) => {
            let a = pos[e.source],
              b = pos[e.target];
            return a && b ? (
              <path
                key={i}
                d={`M${a[0] + 23} ${a[1]} C 320 ${a[1]},320 ${b[1]},${b[0] - 23} ${b[1]}`}
                fill="none"
                style={{ stroke: "var(--graph-edge)" }}
                strokeWidth={Math.min(6, 1 + e.units / 15)}
              >
                <title>
                  {e.source} → {e.target}: {e.units} {e.blood_type}
                </title>
              </path>
            ) : null;
          })}
        {Object.entries(pos).map(([id, [x, y]]) => (
          <g key={id}>
            <circle
              cx={x}
              cy={y}
              r="23"
              style={{
                fill: "var(--surface)",
                stroke:
                  id[0] === "B" ? "var(--graph-bank)" : "var(--graph-hospital)",
              }}
              strokeWidth="2"
            />
            <text
              x={x}
              y={y + 9}
              textAnchor="middle"
              fontSize="29"
              style={{
                fill:
                  id[0] === "B" ? "var(--graph-bank)" : "var(--graph-hospital)",
              }}
            >
              {id[0] === "B" ? "♦" : "+"}
            </text>
            <text
              x={id[0] === "B" ? x : x + 38}
              y={id[0] === "B" ? y + 44 : y}
              textAnchor={id[0] === "B" ? "middle" : "start"}
              fontWeight="700"
            >
              {id}
            </text>
            <text
              className="node"
              x={id[0] === "B" ? x : x + 38}
              y={id[0] === "B" ? y + 63 : y + 20}
              textAnchor={id[0] === "B" ? "middle" : "start"}
            >
              {names[id]}
            </text>
          </g>
        ))}
      </svg>
      {!plan && (
        <p className="caption centered">
          Review the assessment to calculate proposed routes.
        </p>
      )}
    </section>
  );
}
function Transfers({ plan, group }) {
  let rows = (plan?.transfer_proposals || []).filter(
    (r) => group === "all" || r.blood_type === group,
  );
  return (
    <section className="panel" id="transfers">
      <div className="heading">
        <h2>Proposed transfers</h2>
        <small>{rows.length} allocations</small>
      </div>
      {!plan ? (
        <p className="empty">Your reviewed allocation plan will appear here.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {["From", "To", "Group", "Units", "For date", "Evidence"].map(
                  (t) => (
                    <th key={t}>{t}</th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>
                    <b>{r.from_site_id}</b> {names[r.from_site_id]}
                  </td>
                  <td>
                    <b>{r.to_site_id}</b> {names[r.to_site_id]}
                  </td>
                  <td>
                    <span className="blood">{r.blood_type}</span>
                  </td>
                  <td>
                    <b>{r.units}</b>
                  </td>
                  <td>{r.allocation_date}</td>
                  <td>
                    <details>
                      <summary>Unit IDs</summary>
                      <small>{r.unit_ids.join(", ")}</small>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && (
            <p className="empty">No transfers for this group.</p>
          )}
        </div>
      )}
    </section>
  );
}
function Chat({ data }) {
  let [msg, setMsg] = useState([]),
    [q, setQ] = useState(""),
    [busy, setBusy] = useState(false),
    [live, setLive] = useState(false);
  async function send(text) {
    if (!text.trim() || busy) return;
    setQ("");
    setBusy(true);
    setMsg((m) => [...m, { user: true, answer: text }]);
    try {
      let r = await api("chat", {
        assessment_id: data.assessment.assessment_id,
        question: text,
        live,
      });
      setMsg((m) => [...m, r]);
    } catch (e) {
      setMsg((m) => [...m, { answer: e.message }]);
    } finally {
      setBusy(false);
    }
  }
  return (
    <aside>
      <h2>Ask BloodFlow</h2>
      <p>Understand the evidence behind the plan</p>
      <span className="mode">
        ● {live ? "Live data investigation" : "Evidence mode · offline"}
      </span>
      {data.live_available && (
        <label>
          <input
            type="checkbox"
            checked={live}
            onChange={(e) => setLive(e.target.checked)}
          />{" "}
          Use configured OpenAI model
        </label>
      )}
      <div className="chat-history" aria-live="polite">
        <div className="bubble intro">
          <span>✦</span> I can explain this plan, its assumptions, and the
          records behind it.
        </div>
        {!msg.length && (
          <div className="suggestions">
            {[
              "Why does H1 need O-?",
              "What changes in the stress scenario?",
              "How are reserves protected?",
            ].map((text) => (
              <button key={text} onClick={() => send(text)}>
                {text}
                <span>→</span>
              </button>
            ))}
          </div>
        )}
        {msg.map((m, i) => (
          <div key={i} className={"bubble " + (m.user ? "user" : "")}>
            <p>{m.answer}</p>
            {m.evidence_refs && (
              <details>
                <summary>Evidence & tool activity</summary>
                <small>{m.mode}</small>
                <ul>
                  {m.evidence_refs.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
                <pre>{JSON.stringify(m.tool_calls, null, 2)}</pre>
                {m.analysis && (
                  <>
                    <b>Validated live numerical claims</b>
                    <pre>{JSON.stringify(m.analysis.answer, null, 2)}</pre>
                  </>
                )}
              </details>
            )}
          </div>
        ))}
        {busy && (
          <p>Reading evidence{live ? " and running data tools" : ""}…</p>
        )}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(q);
        }}
      >
        <textarea
          aria-label="Ask about this plan"
          placeholder="Ask about this plan…"
          maxLength={2000}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button
          className="primary"
          aria-label="Send question"
          disabled={busy || !q.trim()}
        >
          <Send size={20} />
        </button>
      </form>
      <p className="footnote">ⓘ &nbsp; No shipments are executed.</p>
    </aside>
  );
}
function Modal({ kind, data, busy, close, approve }) {
  let p = data.policy;
  const dialog = useRef(null);
  useEffect(() => {
    function key(e) {
      if (e.key === "Escape") close();
      if (e.key === "Tab") {
        const nodes = dialog.current.querySelectorAll(
          "button:not(:disabled),summary",
        );
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [close]);
  return (
    <div className="scrim" onClick={close}>
      <section
        ref={dialog}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          autoFocus
          className="close"
          onClick={close}
          aria-label="Close dialog"
        >
          ×
        </button>
        <span className="eyebrow">BLOODFLOW / DEMO WORKSPACE</span>
        <h2 id="dialog-title">
          {kind === "review" ? "Review this assessment" : "Demo settings"}
        </h2>
        <p>{data.source}. Snapshot: 22 October 2026, 12:00 Paris.</p>
        <dl>
          {[
            ["Scenario", p.planning],
            ["Planning horizon", p.target_days + " days"],
            ["Target buffer", p.buffer * 100 + "%"],
            [
              "Protected reserves",
              "2 freshest eligible units per bank / group",
            ],
            ["Elapsed exposure today", p.exposure_elapsed * 100 + "%"],
            [
              "Live model",
              data.live_available ? "Configured" : "Not configured",
            ],
          ].map(([k, v]) => (
            <React.Fragment key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </React.Fragment>
          ))}
        </dl>
        {kind === "review" ? (
          <>
            <p>
              This approval records a local demo reviewer and calculates
              hypothetical transfers for this assessment only.
            </p>
            <details>
              <summary>Inspect dated requirements and data issues</summary>
              <pre>
                {JSON.stringify(
                  {
                    requirements: data.assessment.proposed_requirement_updates,
                    issues: data.assessment.unresolved_data_issues,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
            <button
              className="primary approve"
              disabled={busy}
              onClick={approve}
            >
              {busy ? "Calculating…" : "Approve & calculate proposals"}
            </button>
          </>
        ) : (
          <p>
            Live investigation requires OPENAI_API_KEY and OPENAI_MODEL in the
            server environment. Keys are never entered here. Audit records are
            separate from source data.
          </p>
        )}
      </section>
    </div>
  );
}
function App() {
  let [scenario, setScenario] = useState("floor"),
    [group, setGroup] = useState("all"),
    [data, setData] = useState(null),
    [error, setError] = useState(""),
    [modal, setModal] = useState(null),
    [busy, setBusy] = useState(false);
  let [theme, toggleTheme] = useTheme();
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    api("state?scenario=" + scenario)
      .then((d) => {
        if (active) setData(d);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [scenario]);
  const [testKind, setTestKind] = useState("demand_surge");
  async function generateTest() {
    setBusy(true);
    setError("");
    try {
      setData(await api("simulate", { kind: testKind, planning: scenario }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function resetTest() {
    setBusy(true);
    setError("");
    try {
      setData(await api("state?scenario=" + scenario));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function approve() {
    setBusy(true);
    try {
      let plan = await api("optimize", {
        assessment_id: data.assessment.assessment_id,
        confirmed: true,
      });
      setData((d) => ({ ...d, plan }));
      setModal(null);
    } catch (e) {
      setModal(null);
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  let s = data?.plan?.summary;
  return (
    <div className="app">
      <nav aria-label="Main navigation">
        <a className="brand" href="#top">
          B<span>F</span>
        </a>
        <a href="#top">
          <Home size={24} />
          <small>Home</small>
        </a>
        <a href="#network">
          <Network size={24} />
          <small>Network</small>
        </a>
        <a href="#transfers">
          <List size={24} />
          <small>Plan</small>
        </a>
        <button
          className="nav-bottom"
          onClick={toggleTheme}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
        >
          {theme === "dark" ? <Sun size={22} /> : <Moon size={22} />}
          <small>{theme === "dark" ? "Light" : "Dark"}</small>
        </button>
        <button disabled={!data} onClick={() => setModal("settings")}>
          <Settings size={22} />
          <small>Settings</small>
        </button>
      </nav>
      <main id="top">
        <header>
          <div>
            <strong>
              BloodFlow<span>.</span>
            </strong>
            <p>Paris supply planning</p>
          </div>
          <button
            className="settings"
            disabled={!data}
            onClick={() => setModal("settings")}
          >
            ⚙ &nbsp; Demo settings
          </button>
        </header>
        <span className="eyebrow">SUPPLY INTELLIGENCE</span>
        <h1>A clear view of every unit.</h1>
        <p className="subtitle">
          Synthetic dataset · 22 October 2026, 12:00 Paris
        </p>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {!data ? (
          <p className="empty">
            {error ? "Refresh to retry." : "Loading assessment…"}
          </p>
        ) : (
          <>
            <section className="test-inputs" aria-label="Synthetic test inputs">
              <div>
                <b>Test the system</b>
                <p className="caption">
                  Generate independent fake inputs from the original snapshot.
                </p>
              </div>
              <div className="test-actions">
                <select
                  aria-label="Test input type"
                  value={testKind}
                  disabled={busy}
                  onChange={(e) => setTestKind(e.target.value)}
                >
                  <option value="demand_surge">Demand surge</option>
                  <option value="donation">New donations</option>
                  <option value="mixed">Demand + donations</option>
                </select>
                <button disabled={busy} onClick={generateTest}>
                  {busy ? "Working…" : "Generate test scenario"}
                </button>
                {data.simulation && (
                  <button disabled={busy} onClick={resetTest}>
                    Reset to original
                  </button>
                )}
              </div>
              {data.simulation && (
                <div className="simulation-result" role="status">
                  <b>SIMULATED · Seed {data.simulation.seed}</b>
                  <ul>
                    {data.simulation.changes.map((c, i) => (
                      <li key={i}>
                        {c.type === "added_demand"
                          ? "Added demand"
                          : "Added donation"}
                        : {c.units} {c.blood_type} units at {c.site_id} on{" "}
                        {c.date}
                      </li>
                    ))}
                  </ul>
                  <p className="caption">
                    Assessment recalculated. Review and approve to calculate
                    transfers. Switching planning policy returns to the original
                    fixture.
                  </p>
                </div>
              )}
            </section>
            <div className="metrics">
              {[
                [
                  "Planning requirement",
                  data.assessment.proposed_requirement_updates.reduce(
                    (s, r) => s + r.target,
                    0,
                  ),
                ],
                ["Covered", s?.total_met],
                ["Unmet", s?.total_unmet],
                ["Proposed transfers", s?.total_transferred],
              ].map(([k, v], i) => (
                <div key={k}>
                  <span>{k}</span>
                  <strong className={i === 1 ? "teal" : i === 2 ? "red" : ""}>
                    {v ?? "—"}
                  </strong>
                </div>
              ))}
            </div>
            <div className="controls">
              <select
                disabled={busy}
                aria-label="Scenario"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
              >
                <option value="floor">Floor baseline</option>
                <option value="additive_stress">Additive stress</option>
              </select>
              <select
                aria-label="Blood group"
                value={group}
                onChange={(e) => setGroup(e.target.value)}
              >
                <option value="all">All blood groups</option>
                {groups.map((g) => (
                  <option key={g}>{g}</option>
                ))}
              </select>
              <button
                disabled={busy}
                className="primary"
                onClick={() => setModal("review")}
              >
                {data.plan ? "Review approved plan" : "Review & optimize"}
              </button>
            </div>
            <Graph plan={data.plan} group={group} />
            <Transfers plan={data.plan} group={group} />
            <p className="caption">
              {data.plan ? "Approved demo proposal" : "Pending human review"} ·
              Exact blood groups · Expiry-aware allocation · Source records
              preserved
            </p>
          </>
        )}
      </main>
      {data && <Chat key={data.assessment.assessment_id} data={data} />}
      {modal && data && (
        <Modal
          kind={modal}
          data={data}
          busy={busy}
          close={() => !busy && setModal(null)}
          approve={approve}
        />
      )}
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
