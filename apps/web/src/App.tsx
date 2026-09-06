// File: apps/web/src/App.tsx
// Workbench shell for the desktop->web transition (Phase 4.3 preview).
//
// This reproduces the desktop app's validated information architecture —
// the 10-stage StageRail, per-stage rationale, and a provenance ledger —
// with mock data and no backend yet. It exists to make the "glass box"
// thesis concrete and explorable: the AI can never do anything the user
// cannot see, inspect, undo, replay, or fork.
//
// What is real here: the stage IA and copy (ported from
// analysis_orchestrator_service.py) and the log-entry shape (ported from
// AnalysisLogEntry). What is mock: every value, and all interactivity
// beyond stage selection + theme toggle.

import { useMemo, useState } from "react";
import {
  MOCK_LOG,
  STAGES,
  STATUS_PREFIX,
  type LogEntry,
  type StageId,
  type StageStatus,
} from "./pipeline";
import "./App.css";

type Theme = "light" | "dark";

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored =
      typeof localStorage !== "undefined" ? localStorage.getItem("uadas-theme") : null;
    if (stored === "light" || stored === "dark") return stored;
    return typeof matchMedia !== "undefined" &&
      matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  });

  const toggle = () => {
    setTheme((t) => {
      const next: Theme = t === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try {
        localStorage.setItem("uadas-theme", next);
      } catch {
        /* private mode — ignore */
      }
      return next;
    });
  };

  // apply on first render
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-theme", theme);
  }

  return [theme, toggle];
}

// Mock pipeline progress: everything up to `activeIndex` is done.
const ACTIVE_INDEX = 4; // "analyze"

function statusFor(index: number): StageStatus {
  if (index < ACTIVE_INDEX) return "done";
  if (index === ACTIVE_INDEX) return "active";
  return "pending";
}

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const [selected, setSelected] = useState<StageId>("analyze");

  const stage = useMemo(
    () => STAGES.find((s) => s.id === selected) ?? STAGES[0],
    [selected],
  );
  const stageLog = useMemo(
    () => MOCK_LOG.filter((e) => e.stage === selected),
    [selected],
  );

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ▣
          </span>
          <span className="brand-name">Glass-Box Analyst</span>
          <span className="brand-sub">Universal AI Data Analytics Studio</span>
        </div>
        <div className="topbar-right">
          <span className="pill pill-muted">local preview · no backend</span>
          <button className="btn" onClick={toggleTheme}>
            {theme === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
        </div>
      </header>

      <div className="workbench">
        <nav className="stage-rail" aria-label="Analysis pipeline">
          <div className="rail-title">Pipeline</div>
          <ol>
            {STAGES.map((s, i) => {
              const st = statusFor(i);
              return (
                <li key={s.id}>
                  <button
                    className={`stage ${st} ${s.id === selected ? "selected" : ""}`}
                    aria-current={s.id === selected ? "step" : undefined}
                    onClick={() => setSelected(s.id)}
                  >
                    <span className="stage-status" aria-hidden="true">
                      {STATUS_PREFIX[st]}
                    </span>
                    <span className="stage-index">{i + 1}</span>
                    <span className="stage-label">{s.label}</span>
                    {s.autoProposed && (
                      <span className="stage-flag" title="Auto-proposed by the orchestrator">
                        auto
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>

        <main className="stage-detail">
          <div className="detail-head">
            <h1>
              <span className="detail-index">
                {STAGES.findIndex((s) => s.id === stage.id) + 1}
              </span>
              {stage.label}
            </h1>
            <span
              className={`pill ${
                statusFor(STAGES.findIndex((s) => s.id === stage.id)) === "done"
                  ? "pill-ok"
                  : statusFor(STAGES.findIndex((s) => s.id === stage.id)) === "active"
                    ? "pill-accent"
                    : "pill-muted"
              }`}
            >
              {statusFor(STAGES.findIndex((s) => s.id === stage.id))}
            </span>
          </div>

          {stage.rationale ? (
            <p className="rationale">
              <span className="rationale-tag">Why this step</span>
              {stage.rationale}
            </p>
          ) : (
            <p className="rationale rationale-empty">
              Entry / terminal stage — not auto-proposed by the orchestrator.
            </p>
          )}

          <section className="proposal">
            <div className="proposal-head">
              <span className="pill pill-accent">AI proposal</span>
              <span className="proposal-note">
                proposed, not applied — accept or reject
              </span>
            </div>
            <div className="proposal-body">
              <code>
                {stage.id === "analyze"
                  ? "correlation.pearson(dataset_id='ds_02', columns=['ad_spend', 'revenue'])"
                  : `${stage.label.toLowerCase()}.<tool>(dataset_id='ds_02', …)`}
              </code>
              <div className="proposal-actions">
                <button className="btn btn-primary" disabled>
                  Accept
                </button>
                <button className="btn" disabled>
                  Reject
                </button>
                <button className="btn btn-ghost" disabled>
                  Fork a what-if
                </button>
              </div>
            </div>
          </section>

          <section className="ledger">
            <h2>Provenance ledger</h2>
            <p className="ledger-sub">
              Every action is a node: stage · tool · exact inputs · outputs ·
              explanation · timestamp. This is the replay/recipe source.
            </p>
            {stageLog.length === 0 ? (
              <div className="ledger-empty">No recorded actions in this stage yet.</div>
            ) : (
              <ul className="ledger-list">
                {stageLog.map((e, i) => (
                  <LedgerRow key={i} entry={e} />
                ))}
              </ul>
            )}
          </section>
        </main>

        <aside className="context-panel" aria-label="Run context">
          <div className="panel-block">
            <div className="panel-title">Dataset</div>
            <dl>
              <div>
                <dt>active</dt>
                <dd>ds_02</dd>
              </div>
              <div>
                <dt>derived from</dt>
                <dd>ds_01</dd>
              </div>
              <div>
                <dt>rows × cols</dt>
                <dd>18,410 × 9</dd>
              </div>
            </dl>
          </div>
          <div className="panel-block">
            <div className="panel-title">Expertise</div>
            <div className="seg">
              {["beginner", "intermediate", "expert"].map((lvl) => (
                <button
                  key={lvl}
                  className={`seg-item ${lvl === "intermediate" ? "on" : ""}`}
                  disabled
                >
                  {lvl}
                </button>
              ))}
            </div>
            <p className="panel-hint">
              Re-ranks guidance and disclosure — never hides an action.
            </p>
          </div>
          <div className="panel-block">
            <div className="panel-title">Full log</div>
            <ol className="mini-log">
              {MOCK_LOG.map((e, i) => (
                <li key={i}>
                  <button className="mini-log-item" onClick={() => setSelected(e.stage)}>
                    <span className="mini-log-stage">{e.stage}</span>
                    <span className="mini-log-tool">{e.toolName}</span>
                  </button>
                </li>
              ))}
            </ol>
          </div>
        </aside>
      </div>

      <footer className="statusline">
        <span>10-stage pipeline</span>
        <span>·</span>
        <span>{MOCK_LOG.length} recorded actions</span>
        <span>·</span>
        <span>ported IA from analysis_orchestrator_service.py</span>
        <span>·</span>
        <span>Phase 4.3 preview</span>
      </footer>
    </div>
  );
}

function LedgerRow({ entry }: { entry: LogEntry }) {
  const [open, setOpen] = useState(true);
  return (
    <li className="ledger-row">
      <button className="ledger-row-head" onClick={() => setOpen((o) => !o)}>
        <span className="ledger-tool">{entry.toolName}</span>
        <span className="ledger-time">{entry.timestamp.replace("T", " ").replace("Z", " UTC")}</span>
        <span className="ledger-caret" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <div className="ledger-row-body">
          <p className="ledger-explain">{entry.explanation}</p>
          <div className="ledger-io">
            <div>
              <span className="io-tag">inputs</span>
              <pre>{JSON.stringify(entry.inputs, null, 2)}</pre>
            </div>
            <div>
              <span className="io-tag">outputs</span>
              <pre>{JSON.stringify(entry.outputs, null, 2)}</pre>
            </div>
          </div>
        </div>
      )}
    </li>
  );
}
