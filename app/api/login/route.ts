import { NextRequest, NextResponse } from "next/server";
import {
  authenticateWithPassword,
  createSessionToken,
  sessionCookieOptions,
} from "../../../lib/auth";
import { envCredentials, getSessionCookieName } from "../../../lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  let body: { username?: string; password?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const username = String(body.username || "").trim();
  const password = String(body.password || "");
  if (!username || !password) {
    return NextResponse.json(
      { error: "Username and password required." },
      { status: 400 }
    );
  }

  const result = await authenticateWithPassword(username, password);
  if (!result.ok) {
    if (result.reason === "missing") {
      return NextResponse.json(
        {
          error:
            "Login not ready. Start BeaconConsoleBridge.exe on the PC first (or set CONSOLE_USERNAME + CONSOLE_PASSWORD on Vercel).",
        },
        { status: 401 }
      );
    }
    const hint = envCredentials()
      ? "Use the CONSOLE_USERNAME / CONSOLE_PASSWORD from Vercel."
      : "Use the exact username/password set on the PC bridge.";
    return NextResponse.json(
      { error: `Wrong username or password. ${hint}` },
      { status: 401 }
    );
  }

  const token = await createSessionToken(result.state.username, "viewer");
  const res = NextResponse.json({
    ok: true,
    username: result.state.username,
    botLabel: result.state.botLabel,
  });
  res.cookies.set(
    getSessionCookieName(),
    token,
    sessionCookieOptions(60 * 60 * 24 * 7)
  );
  return res;
}
