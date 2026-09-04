"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useRouter } from "next/navigation";

type LogLine = { id: number; t: number; text: string };

export default function ConsolePage() {
  const router = useRouter();
  const [lines, setLines] = useState<LogLine[]>([]);
  const [online, setOnline] = useState(false);
  const [botRunning, setBotRunning] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [controlMsg, setControlMsg] = useState("");
  const [botLabel, setBotLabel] = useState("smmod");
  const [username, setUsername] = useState("");
  const afterRef = useRef(0);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function tick() {
      try {
        const res = await fetch(`/api/logs?after=${afterRef.current}`, {
          cache: "no-store",
        });
        if (res.status === 401 || res.status === 404) {
          router.replace("/");
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        setOnline(Boolean(data.online));
        setBotRunning(Boolean(data.botRunning));
        setPending(data.pendingCommand?.action || null);
        setBotLabel(data.botLabel || "smmod");
        setUsername(data.username || "");
        if (Array.isArray(data.lines) && data.lines.length) {
          setLines((prev) => {
            const wiped = data.lines.some((l: LogLine) =>
              String(l.text).includes("old logs wiped")
            );
            const merged = wiped
              ? data.lines
              : afterRef.current === 0
                ? data.lines
                : [...prev, ...data.lines];
            const last = merged[merged.length - 1];
            if (last) afterRef.current = last.id;
            return merged.slice(-2000);
          });
        }
      } catch {
        // keep polling
      }
      if (!cancelled) timer = setTimeout(tick, 900);
    }

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [router]);

  useEffect(() => {
    if (!stickRef.current) return;
    const el = scrollerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  async function logout() {
    await fetch("/api/logout", { method: "POST" });
    router.replace("/");
  }

  async function sendControl(action: "start" | "stop") {
    setBusy(true);
    setControlMsg("");
    try {
      const res = await fetch("/api/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const data = await res.json();
      if (!res.ok) {
        setControlMsg(data.error || "Failed");
      } else {
        setControlMsg(`Sent ${action} — waiting for PC…`);
        setPending(action);
      }
    } catch {
      setControlMsg("Could not reach server.");
    }
    setBusy(false);
  }

  const statusLabel = !online
    ? "BRIDGE OFFLINE"
    : botRunning
      ? "BOT RUNNING"
      : "BOT STOPPED";

  return (
    <main
      style={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        position: "relative",
        zIndex: 1,
      }}
    >
      <header
        className="fade-in"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "1rem",
          padding: "0.85rem 1.1rem",
          borderBottom: "1px solid var(--line)",
          background: "rgba(5,8,6,0.82)",
          backdropFilter: "blur(8px)",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.75rem" }}>
          <strong
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "1.35rem",
              letterSpacing: "-0.03em",
              color: "var(--phosphor)",
            }}
          >
            BEACON
          </strong>
          <span style={{ color: "var(--muted)", fontSize: "0.78rem" }}>
            {botLabel}.py
          </span>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.65rem",
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.45rem",
              fontSize: "0.72rem",
              color:
                !online
                  ? "var(--danger)"
                  : botRunning
                    ? "var(--phosphor)"
                    : "var(--amber)",
              letterSpacing: "0.06em",
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background:
                  !online
                    ? "var(--danger)"
                    : botRunning
                      ? "var(--phosphor)"
                      : "var(--amber)",
                animation: botRunning ? "pulse-dot 1.6s infinite" : undefined,
              }}
            />
            {statusLabel}
          </span>

          <button
            type="button"
            disabled={busy || !online || botRunning || pending === "start"}
            onClick={() => sendControl("start")}
            style={btnStyle(true, busy || !online || botRunning)}
          >
            Start
          </button>
          <button
            type="button"
            disabled={busy || !online || !botRunning || pending === "stop"}
            onClick={() => sendControl("stop")}
            style={btnStyle(false, busy || !online || !botRunning)}
          >
            Stop
          </button>

          <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>
            {username}
          </span>
          <button
            type="button"
            onClick={logout}
            style={{
              border: "1px solid var(--line)",
              background: "transparent",
              color: "var(--muted)",
              padding: "0.35rem 0.65rem",
              cursor: "pointer",
              fontSize: "0.72rem",
            }}
          >
            Log out
          </button>
        </div>
      </header>

      {controlMsg ? (
        <div
          style={{
            padding: "0.4rem 1.1rem",
            fontSize: "0.75rem",
            color: "var(--amber)",
            borderBottom: "1px solid var(--line)",
          }}
        >
          {controlMsg}
          {pending ? ` (pending: ${pending})` : ""}
        </div>
      ) : null}

      <div
        ref={scrollerRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stickRef.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
        style={{
          flex: 1,
          overflow: "auto",
          padding: "1rem 1.1rem 2rem",
          fontSize: "0.86rem",
          lineHeight: 1.45,
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.35), rgba(0,0,0,0.55))",
        }}
        aria-live="polite"
      >
        <div
          style={{
            color: "var(--muted)",
            marginBottom: "0.75rem",
            fontSize: "0.75rem",
          }}
        >
          C:\Windows\System32\cmd.exe — py {botLabel}.py
        </div>
        {lines.map((line) => (
          <div
            key={line.id}
            style={{
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              color: colorFor(line.text),
            }}
          >
            {line.text}
          </div>
        ))}
        <div
          aria-hidden
          style={{
            display: "inline-block",
            width: "0.55ch",
            height: "1.1em",
            background: "var(--phosphor)",
            verticalAlign: "text-bottom",
            marginLeft: 2,
            animation: "blink 1.05s step-end infinite",
          }}
        />
      </div>

      <footer
        style={{
          borderTop: "1px solid var(--line)",
          padding: "0.55rem 1.1rem",
          color: "var(--muted)",
          fontSize: "0.7rem",
          display: "flex",
          justifyContent: "space-between",
          gap: "1rem",
          background: "rgba(5,8,6,0.9)",
        }}
      >
        <span>Start / Stop smmod on the PC · no shell / no free typing</span>
        <span>{lines.length} lines</span>
      </footer>
    </main>
  );
}

function btnStyle(isStart: boolean, disabled: boolean): CSSProperties {
  const color = isStart ? "var(--phosphor)" : "var(--danger)";
  return {
    border: `1px solid ${color}`,
    background: disabled
      ? "transparent"
      : isStart
        ? "rgba(61,255,122,0.12)"
        : "rgba(255,92,92,0.12)",
    color,
    padding: "0.4rem 0.85rem",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: "0.75rem",
    fontWeight: 600,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    opacity: disabled ? 0.4 : 1,
  };
}

function colorFor(text: string): string {
  const t = text.toLowerCase();
  if (t.includes("error") || t.includes("traceback") || t.includes("exception")) {
    return "var(--danger)";
  }
  if (t.includes("warn") || t.includes("remote stop") || t.includes("remote start")) {
    return "var(--amber)";
  }
  if (t.startsWith("[beacon]")) return "var(--phosphor-dim)";
  return "var(--text)";
}
