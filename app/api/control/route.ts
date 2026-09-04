import { NextRequest, NextResponse } from "next/server";
import { readSession, verifyAgentBearer } from "../../../lib/auth";
import {
  isOnline,
  loadState,
  normalizeUsername,
  queueCommand,
  takePendingCommand,
  type ControlAction,
} from "../../../lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Viewer: queue start/stop for the PC bridge. */
export async function POST(req: NextRequest) {
  const session = await readSession();
  if (!session) {
    return NextResponse.json({ error: "Not logged in" }, { status: 401 });
  }

  let body: { action?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const action = String(body.action || "").toLowerCase() as ControlAction;
  if (action !== "start" && action !== "stop") {
    return NextResponse.json(
      { error: 'action must be "start" or "stop"' },
      { status: 400 }
    );
  }

  const state = await loadState();
  if (!state || normalizeUsername(state.username) !== session.u) {
    return NextResponse.json({ error: "No console" }, { status: 404 });
  }

  const result = await queueCommand(action, session.u);
  if (!result.ok) {
    return NextResponse.json({ error: result.error }, { status: 409 });
  }

  return NextResponse.json({
    ok: true,
    command: result.command,
    message: `Sent ${action} to the PC bridge.`,
  });
}

/**
 * Bridge: pull pending command (agent bearer).
 * Also returns botRunning / online for sync.
 */
export async function GET(req: NextRequest) {
  const bearer = await verifyAgentBearer(req.headers.get("authorization"));
  const session = bearer ? null : await readSession();

  if (!bearer && !session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const state = await loadState();
  if (!state) {
    return NextResponse.json({ error: "No console" }, { status: 404 });
  }

  const who = bearer?.u || session!.u;
  if (normalizeUsername(state.username) !== who) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  // Only the bridge (agent) consumes/clears the command
  let command = null;
  if (bearer) {
    command = await takePendingCommand();
  } else {
    command = state.pendingCommand || null;
  }

  return NextResponse.json({
    ok: true,
    command,
    botRunning: Boolean(state.botRunning),
    online: isOnline(state),
    bridgeOnline: isOnline(state),
  });
}
