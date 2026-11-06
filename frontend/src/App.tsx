import { useEffect, useRef, useState } from "react";

type Line = { kind: string; text: string };
type OutFile = { id: string; filename: string; size: number };

// One session event, as the backend forwards it from the Anthropic API.
type AgentEvent = {
  type: string;
  agent_name?: string;
  from_agent_name?: string;
  to_agent_name?: string;
  name?: string;
  message?: string;
  stop_reason?: { type: string };
  content?: { type: string; text?: string }[];
};

function describe(e: AgentEvent): Line | null {
  switch (e.type) {
    case "session.thread_created":
      return { kind: "thread", text: `thread spawned: ${e.agent_name}` };
    case "agent.thread_message_sent":
      return { kind: "delegate", text: `delegate → ${e.to_agent_name}` };
    case "agent.thread_message_received":
      return { kind: "reply", text: `reply ← ${e.from_agent_name}` };
    case "agent.tool_use":
      return { kind: "tool", text: `tool: ${e.name}` };
    case "agent.message":
      return { kind: "text", text: (e.content ?? []).map((b) => b.text ?? "").join("") };
    case "session.status_idle":
      // requires_action means it waits on us, not that it is done.
      return e.stop_reason?.type === "requires_action" ? null : { kind: "done", text: "swarm finished" };
    case "error":
      return { kind: "error", text: e.message ?? "error" };
    default:
      return null;
  }
}

export function App() {
  const [rfp, setRfp] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [files, setFiles] = useState<OutFile[]>([]);
  const [session, setSession] = useState<{ id: string; console: string } | null>(null);
  const [running, setRunning] = useState(false);
  const logEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/rfp").then((r) => r.json()).then((d) => setRfp(d.rfp));
  }, []);
  useEffect(() => logEnd.current?.scrollIntoView({ block: "end" }), [lines]);

  async function run() {
    setRunning(true);
    setLines([]);
    setFiles([]);
    const res = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rfp }),
    });
    if (!res.ok) {
      setLines([{ kind: "error", text: await res.text() }]);
      setRunning(false);
      return;
    }
    const { session_id, console } = await res.json();
    setSession({ id: session_id, console });

    const source = new EventSource(`/api/runs/${session_id}/events`);
    source.onmessage = (msg) => {
      const line = describe(JSON.parse(msg.data));
      if (line) setLines((prev) => [...prev, line]);
    };
    // The backend closes the stream when the swarm is done.
    source.onerror = async () => {
      source.close();
      setRunning(false);
      // Output files show up in the Files API a few seconds after the end.
      await new Promise((r) => setTimeout(r, 3000));
      setFiles(await fetch(`/api/runs/${session_id}/files`).then((r) => r.json()));
    };
  }

  return (
    <main>
      <header>
        <h1>Deal Desk</h1>
        <p>A coordinator and four specialists answer an RFP.</p>
      </header>
      <section className="input">
        <textarea value={rfp} onChange={(e) => setRfp(e.target.value)} rows={14} />
        <button onClick={run} disabled={running || !rfp}>
          {running ? "Running…" : "Run the swarm"}
        </button>
        {session && (
          <a href={session.console} target="_blank" rel="noreferrer">
            Session in the Claude Console
          </a>
        )}
      </section>
      <section className="log">
        {lines.map((l, i) => (
          <div key={i} className={`line ${l.kind}`}>
            {l.text}
          </div>
        ))}
        <div ref={logEnd} />
      </section>
      {files.length > 0 && (
        <section className="files">
          <h2>Deliverables</h2>
          {files.map((f) => (
            <a key={f.id} href={`/api/files/${f.id}?name=${encodeURIComponent(f.filename)}`}>
              {f.filename} ({Math.round(f.size / 1024)} KB)
            </a>
          ))}
        </section>
      )}
    </main>
  );
}
