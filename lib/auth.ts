import { SignJWT, jwtVerify } from "jose";
import { cookies } from "next/headers";
import {
  envCredentials,
  getSessionCookieName,
  hashPassword,
  loadState,
  normalizeUsername,
  saveState,
  sessionSecret,
  verifyPassword,
  type ConsoleState,
} from "./store";

export type SessionPayload = {
  u: string;
  role: "viewer" | "agent";
};

export async function createSessionToken(
  username: string,
  role: "viewer" | "agent" = "viewer"
): Promise<string> {
  return new SignJWT({ u: normalizeUsername(username), role })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(role === "agent" ? "30d" : "7d")
    .sign(sessionSecret());
}

export async function readSession(): Promise<SessionPayload | null> {
  const jar = await cookies();
  const token = jar.get(getSessionCookieName())?.value;
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, sessionSecret());
    const u = normalizeUsername(String(payload.u || ""));
    const role = payload.role === "agent" ? "agent" : "viewer";
    if (!u) return null;
    return { u, role };
  } catch {
    return null;
  }
}

export async function verifyAgentBearer(
  authHeader: string | null
): Promise<SessionPayload | null> {
  if (!authHeader?.startsWith("Bearer ")) return null;
  const token = authHeader.slice(7).trim();
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, sessionSecret());
    const u = normalizeUsername(String(payload.u || ""));
    if (!u || payload.role !== "agent") return null;
    return { u, role: "agent" };
  } catch {
    return null;
  }
}

export type AuthFail = { ok: false; reason: "missing" | "wrong" };
export type AuthOk = { ok: true; state: ConsoleState };

/**
 * Validates viewer/agent password.
 * Prefers durable Vercel env CONSOLE_USERNAME / CONSOLE_PASSWORD when set
 * (required for multiple people logging in on serverless).
 */
export async function authenticateWithPassword(
  username: string,
  password: string
): Promise<AuthOk | AuthFail> {
  const user = normalizeUsername(username);
  const env = envCredentials();

  if (env) {
    if (user !== env.username || password !== env.password) {
      return { ok: false, reason: "wrong" };
    }
    let state = await loadState();
    if (!state || normalizeUsername(state.username) !== env.username) {
      state = {
        username: env.username,
        passwordHash: hashPassword(env.password),
        salt: "",
        lines: state?.lines?.length
          ? state.lines
          : [
              {
                id: 1,
                t: Date.now(),
                text: `[beacon] Waiting for bridge / bot output…`,
              },
            ],
        nextId: state?.nextId || 2,
        lastHeartbeat: state?.lastHeartbeat || 0,
        botLabel: state?.botLabel || "smmod",
        claimedAt: state?.claimedAt || Date.now(),
      };
      await saveState(state);
    }
    return { ok: true, state };
  }

  const state = await loadState();
  if (!state) return { ok: false, reason: "missing" };
  if (normalizeUsername(state.username) !== user) {
    return { ok: false, reason: "wrong" };
  }
  if (!verifyPassword(password, state.passwordHash)) {
    return { ok: false, reason: "wrong" };
  }
  return { ok: true, state };
}

export function sessionCookieOptions(maxAgeSec: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge: maxAgeSec,
  };
}
