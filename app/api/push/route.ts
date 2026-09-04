import { NextRequest, NextResponse } from "next/server";
import {
  authenticateWithPassword,
  verifyAgentBearer,
} from "../../../lib/auth";
import {
  appendLines,
  envCredentials,
  hashPassword,
  loadState,
  normalizeUsername,
  saveState,
} from "../../../lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * PC bridge pushes console lines here. Read-only replication — no commands.
 */
export async function POST(req: NextRequest) {
  let body: {
    username?: string;
    password?: string;
    lines?: string[];
    botLabel?: string;
  };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const bearer = await verifyAgentBearer(req.headers.get("authorization"));
  let ok = false;
  if (bearer) {
    let state = await loadState();
    if (!state || normalizeUsername(state.username) !== bearer.u) {
      const env = envCredentials();
      if (env && env.username === bearer.u) {
        state = {
          username: env.username,
          passwordHash: hashPassword(env.password),
          salt: "",
          lines: state?.lines || [],
          nextId: state?.nextId || 1,
          lastHeartbeat: Date.now(),
          botLabel: state?.botLabel || "smmod",
          claimedAt: state?.claimedAt || Date.now(),
        };
        await saveState(state);
      }
    }
    state = await loadState();
    ok = Boolean(state && normalizeUsername(state.username) === bearer.u);
  } else {
    const username = String(body.username || "").trim();
    const password = String(body.password || "");
    const auth = await authenticateWithPassword(username, password);
    ok = auth.ok;
  }

  if (!ok) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const lines = Array.isArray(body.lines) ? body.lines.map(String) : [];
  if (lines.length > 200) {
    return NextResponse.json(
      { error: "Max 200 lines per push." },
      { status: 400 }
    );
  }

  const total = await appendLines(lines, body.botLabel);
  return NextResponse.json({ ok: true, total });
}
