import { NextRequest, NextResponse } from "next/server";
import {
  authenticateWithPassword,
  verifyAgentBearer,
} from "../../../lib/auth";
import {
  envCredentials,
  hashPassword,
  loadState,
  normalizeUsername,
  saveState,
  touchHeartbeat,
} from "../../../lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  let body: {
    username?: string;
    password?: string;
    botLabel?: string;
    botRunning?: boolean;
  } = {};
  try {
    body = await req.json();
  } catch {
    // empty body ok if bearer present
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
    const auth = await authenticateWithPassword(
      String(body.username || "").trim(),
      String(body.password || "")
    );
    ok = auth.ok;
  }

  if (!ok) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  await touchHeartbeat(body.botLabel, body.botRunning);
  return NextResponse.json({ ok: true });
}
