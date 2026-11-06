import { useEffect, useRef, useState } from "react";

// One event from the backend (rfp_orchestrator.events.Event, plus run_error / stream_end).
type RunEvent = {
  type: string;
  run_id: string;
  agent_id?: string | null;
  agent_name?: string | null;
  parent_id?: string | null;
  depth?: number | null;
  data: Record<string, any>;
  ts?: number;
};

type Agent = {
  id: string;
  name: string;
  parentId: string | null;
  depth: number;
  model: string;
  task: string;
  status: "running" | "done" | "error";
  durationS?: number;
  outputTokens?: number;
  report?: string;
};

type Line = { kind: string; depth: number; text: string };
type OutFile = { path: string; area: string; size: number };

const short = (s: string, n = 140) => {
  const t = String(s ?? "").replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
};

function describe(e: RunEvent): Line | null {
  const depth = e.depth ?? 0;
  const who = e.agent_name ?? "";
  switch (e.type) {
    case "run_started":
      return { kind: "thread", depth: 0, text: "run started" };
    case "agent_started":
      return { kind: "thread", depth, text: `▶ ${who} started: ${short(e.data.task)}` };
    case "agent_tool_call":
      if (e.data.tool === "delegate")
        return { kind: "delegate", depth, text: `${who} → delegate to ${e.data.input?.agent}` };
      return { kind: "tool", depth, text: `${who} · ${e.data.tool} ${short(JSON.stringify(e.data.input ?? {}), 80)}` };
    case "delegation_rejected":
      return { kind: "error", depth, text: `✗ ${who}: delegation rejected (${e.data.reason})` };
    case "file_written":
      return { kind: "reply", depth, text: `💾 ${e.data.path}` };
    case "agent_finished":
      return {
        kind: "reply",
        depth,
        text: `✔ ${who} done in ${Math.round(e.data.duration_s ?? 0)}s (${e.data.usage?.output_tokens ?? 0} output tokens)`,
      };
    case "agent_error":
      return { kind: "error", depth, text: `! ${who}: ${e.data.error}` };
    case "run_error":
      return { kind: "error", depth: 0, text: `run failed: ${e.data.error}` };
    case "run_finished":
      return { kind: "done", depth: 0, text: `run finished (${e.data.summary?.agents ?? "?"} agents)` };
    default:
      return null;
  }
}

function applyToAgents(agents: Record<string, Agent>, e: RunEvent): Record<string, Agent> {
  if (!e.agent_id) return agents;
  const prev = agents[e.agent_id];
  switch (e.type) {
    case "agent_started":
      return {
        ...agents,
        [e.agent_id]: {
          id: e.agent_id,
          name: e.agent_name ?? "?",
          parentId: e.parent_id ?? null,
          depth: e.depth ?? 0,
          model: e.data.model,
          task: e.data.task,
          status: "running",
        },
      };
    case "agent_finished":
      if (!prev) return agents;
      return {
        ...agents,
        [e.agent_id]: {
          ...prev,
          status: e.data.ok ? "done" : "error",
          durationS: e.data.duration_s,
          outputTokens: e.data.usage?.output_tokens,
          report: e.data.report,
        },
      };
    case "agent_error":
      return prev ? { ...agents, [e.agent_id]: { ...prev, status: "error" } } : agents;
    default:
      return agents;
  }
}

function AgentTree({ agents, parentId }: { agents: Record<string, Agent>; parentId: string | null }) {
  const children = Object.values(agents).filter((a) => a.parentId === parentId);
  if (children.length === 0) return null;
  return (
    <ul className="tree">
      {children.map((a) => (
        <li key={a.id}>
          <details>
            <summary>
              <span className={`dot ${a.status}`} />
              <strong>{a.name}</strong> <span className="muted">{a.model.replace("claude-", "")}</span>
              {a.durationS !== undefined && <span className="muted"> · {Math.round(a.durationS)}s</span>}
            </summary>
            <div className="detail">
              <div className="label">Task</div>
              <pre>{a.task}</pre>
              {a.report && (
                <>
                  <div className="label">Report</div>
                  <pre>{a.report}</pre>
                </>
              )}
            </div>
          </details>
          <AgentTree agents={agents} parentId={a.id} />
        </li>
      ))}
    </ul>
  );
}

export function App() {
  const [rfp, setRfp] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [agents, setAgents] = useState<Record<string, Agent>>({});
  const [files, setFiles] = useState<OutFile[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const logEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/rfp").then((r) => r.json()).then((d) => setRfp(d.rfp));
  }, []);
  useEffect(() => logEnd.current?.scrollIntoView({ block: "end" }), [lines]);

  async function run() {
    setRunning(true);
    setLines([]);
    setAgents({});
    setFiles([]);
    const res = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rfp }),
    });
    if (!res.ok) {
      setLines([{ kind: "error", depth: 0, text: await res.text() }]);
      setRunning(false);
      return;
    }
    const { run_id } = await res.json();
    setRunId(run_id);

    const source = new EventSource(`/api/runs/${run_id}/events`);
    // The backend replays the whole history on every (re)connect, so start fresh.
    source.onopen = () => {
      setLines([]);
      setAgents({});
    };
    source.onmessage = async (msg) => {
      const e: RunEvent = JSON.parse(msg.data);
      if (e.type === "stream_end") {
        source.close();
        setRunning(false);
        setFiles(await fetch(`/api/runs/${run_id}/files`).then((r) => r.json()));
        return;
      }
      setAgents((prev) => applyToAgents(prev, e));
      const line = describe(e);
      if (line) setLines((prev) => [...prev, line]);
    };
    // On a network error EventSource reconnects by itself; onopen resets the view.
  }

  const finals = files.filter((f) => f.area === "final");
  const work = files.filter((f) => f.area === "work");
  const fileLink = (f: OutFile) => (
    <a key={f.path} href={`/api/runs/${runId}/files/${f.path}`}>
      {f.path} ({Math.max(1, Math.round(f.size / 1024))} KB)
    </a>
  );
  const agentList = Object.values(agents);

  return (
    <main>
      <header>
        <h1>RFP Agent Team</h1>
        <p>
          A bid lead orchestrates specialists, each of which can send out up to three helpers, and delivers a
          proposal document.
        </p>
      </header>
      <section className="input">
        <textarea value={rfp} onChange={(e) => setRfp(e.target.value)} rows={12} />
        <button onClick={run} disabled={running || rfp.length < 50}>
          {running ? "Running…" : "Run the agent team"}
        </button>
      </section>
      {(agentList.length > 0 || lines.length > 0) && (
        <section className="board">
          <div className="panel">
            <h2>
              Agents{" "}
              <span className="muted">
                {agentList.filter((a) => a.status === "running").length} running · {agentList.length} total
              </span>
            </h2>
            <AgentTree agents={agents} parentId={null} />
          </div>
          <div className="log">
            {lines.map((l, i) => (
              <div key={i} className={`line ${l.kind}`} style={{ paddingLeft: `${l.depth * 1.2}rem` }}>
                {l.text}
              </div>
            ))}
            <div ref={logEnd} />
          </div>
        </section>
      )}
      {files.length > 0 && (
        <section className="files">
          <h2>Deliverables</h2>
          {finals.length > 0 ? finals.map(fileLink) : <span className="muted">No final document was written.</span>}
          {work.length > 0 && (
            <details>
              <summary>Working files ({work.length})</summary>
              <div className="files">{work.map(fileLink)}</div>
            </details>
          )}
        </section>
      )}
    </main>
  );
}
