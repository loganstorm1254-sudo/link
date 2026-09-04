#!/usr/bin/env python3
"""
Beacon Console Bridge
---------------------
Runs on your server PC. Captures stdout/stderr from your smmod folder
(smmod/smmod.py or any exe) and pushes it to your Vercel console site.
View-only on the website — no remote typing / no shell access.

Usage (Windows):
  py bridge.py
  py bridge.py --bot-dir "C:\\path\\to\\smmod"
  py bridge.py --cmd "py smmod.py" --bot-dir "D:\\bots\\smmod"
  py bridge.py --cmd "Beacon.exe"

First run asks for:
  - Website URL (https://your-app.vercel.app)
  - Username
  - Password
  - Path to your smmod folder (the folder that contains smmod.py)

Config is saved next to this script as bridge_config.json
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from getpass import getpass
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "bridge_config.json"
DEFAULT_CMD = "py smmod.py"


def find_smmod_dir() -> Path | None:
    """Look for a folder named smmod that contains smmod.py."""
    candidates = [
        Path.cwd() / "smmod",
        Path.cwd(),
        BASE_DIR / "smmod",
        BASE_DIR.parent / "smmod",
        BASE_DIR.parent.parent / "smmod",
    ]
    # Also walk a couple levels up looking for smmod/smmod.py
    here = Path.cwd().resolve()
    for parent in [here, *here.parents[:3]]:
        candidates.append(parent / "smmod")
        candidates.append(parent)

    seen: set[Path] = set()
    for raw in candidates:
        try:
            path = raw.resolve()
        except Exception:
            continue
        if path in seen:
            continue
        seen.add(path)
        if (path / "smmod.py").is_file():
            return path
    return None


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.is_file():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def normalize_base(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


def http_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {"Accept": "application/json", "User-Agent": "BeaconBridge/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"raw": raw}
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"error": raw or str(e)}
        return e.code, parsed
    except Exception as e:
        return 0, {"error": str(e)}


def resolve_bot_dir(raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw.strip().strip('"')).expanduser()
    try:
        path = path.resolve()
    except Exception:
        return None
    if path.is_file() and path.name.lower() == "smmod.py":
        return path.parent
    if path.is_dir():
        return path
    return None


def prompt_setup(existing: dict[str, Any]) -> dict[str, Any]:
    print()
    print("=== Beacon Console Bridge ===")
    print("This links your local bot CMD output to the Vercel website.")
    print("The website is READ-ONLY (no typing / no remote control).")
    print()

    base = existing.get("base_url") or ""
    user = existing.get("username") or ""
    cmd = existing.get("command") or DEFAULT_CMD
    detected = find_smmod_dir()
    bot_dir = existing.get("bot_dir") or (str(detected) if detected else "")

    entered = input(f"Website URL [{base or 'https://....vercel.app'}]: ").strip()
    if entered:
        base = entered
    if not base:
        print("URL is required.")
        sys.exit(1)
    base = normalize_base(base)

    entered = input(f"Username [{user or 'admin'}]: ").strip()
    if entered:
        user = entered
    if not user:
        user = "admin"

    password = getpass("Password (hidden): ").strip()
    if not password:
        if existing.get("password"):
            password = str(existing["password"])
            print("(reusing saved password)")
        else:
            print("Password is required.")
            sys.exit(1)

    print()
    print("Your bot lives in a folder (example: ...\\smmod\\smmod.py).")
    hint = bot_dir or r"C:\path\to\smmod"
    entered = input(f"Path to smmod folder [{hint}]: ").strip().strip('"')
    if entered:
        bot_dir = entered
    resolved = resolve_bot_dir(bot_dir)
    if not resolved:
        print("Could not find that folder. Example: C:\\Users\\You\\smmod")
        sys.exit(1)
    if not (resolved / "smmod.py").is_file():
        print(f"Warning: no smmod.py inside {resolved}")
        print("You can still set a custom command below.")
    bot_dir = str(resolved)

    entered = input(f"Command to run inside that folder [{cmd}]: ").strip()
    if entered:
        cmd = entered

    cfg = {
        "base_url": base,
        "username": user,
        "password": password,
        "command": cmd,
        "bot_dir": bot_dir,
        "bot_label": "smmod",
        "agent_token": existing.get("agent_token") or "",
    }
    save_config(cfg)
    print(f"\nSaved config → {CONFIG_PATH}")
    print(f"Bot folder   → {bot_dir}")
    return cfg


def claim(cfg: dict[str, Any], force: bool = False) -> str:
    status, data = http_json(
        "POST",
        f"{cfg['base_url']}/api/claim",
        {
            "username": cfg["username"],
            "password": cfg["password"],
            "botLabel": cfg.get("bot_label") or "smmod",
            "force": force,
        },
    )
    if status != 200 or not data.get("ok"):
        err = data.get("error") or f"HTTP {status}"
        print(f"[bridge] Claim failed: {err}")
        if "already claimed" in str(err).lower() or status == 403:
            ans = input("Reclaim with force? [y/N]: ").strip().lower()
            if ans == "y":
                return claim(cfg, force=True)
        sys.exit(1)
    token = str(data.get("agentToken") or "")
    if not token:
        print("[bridge] Claim succeeded but no agentToken returned.")
        sys.exit(1)
    cfg["agent_token"] = token
    save_config(cfg)
    print("[bridge] Console claimed on Vercel.")
    return token


def push_lines(cfg: dict[str, Any], lines: list[str]) -> bool:
    if not lines:
        return True
    status, data = http_json(
        "POST",
        f"{cfg['base_url']}/api/push",
        {"lines": lines, "botLabel": cfg.get("bot_label") or "smmod"},
        token=cfg.get("agent_token") or None,
    )
    if status == 401:
        # token expired / secret rotated — re-claim
        claim(cfg)
        status, data = http_json(
            "POST",
            f"{cfg['base_url']}/api/push",
            {"lines": lines, "botLabel": cfg.get("bot_label") or "smmod"},
            token=cfg.get("agent_token") or None,
        )
    return status == 200 and bool(data.get("ok"))


def heartbeat(cfg: dict[str, Any]) -> None:
    http_json(
        "POST",
        f"{cfg['base_url']}/api/heartbeat",
        {"botLabel": cfg.get("bot_label") or "smmod"},
        token=cfg.get("agent_token") or None,
        timeout=10.0,
    )


def reader_thread(stream, label: str, out_q: queue.Queue[str]) -> None:
    try:
        for raw in iter(stream.readline, b""):
            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                text = str(raw)
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            if text.endswith("\n"):
                text = text[:-1]
            # Still print locally so the CMD window looks normal
            try:
                sys.stdout.write(text + "\n")
                sys.stdout.flush()
            except Exception:
                pass
            out_q.put(text)
    finally:
        try:
            stream.close()
        except Exception:
            pass
        out_q.put(f"[bridge] ({label} closed)")


def run_command(cfg: dict[str, Any]) -> int:
    cmd = str(cfg.get("command") or DEFAULT_CMD)
    bot_dir = resolve_bot_dir(cfg.get("bot_dir")) or find_smmod_dir() or Path.cwd()
    if not bot_dir.is_dir():
        print(f"[bridge] Bot folder not found: {bot_dir}")
        sys.exit(1)

    print(f"[bridge] Bot folder: {bot_dir}")
    print(f"[bridge] Starting: {cmd}")
    print(f"[bridge] Streaming to: {cfg['base_url']}")
    print("[bridge] Website is view-only. Close this window to stop.\n")

    # shell=True so Windows users can pass "py smmod.py" or paths with spaces
    # cwd = smmod folder so relative files next to smmod.py still work
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # Keep a visible console — do NOT hide the window; user wants CMD output
        creationflags = 0

    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        cwd=str(bot_dir),
    )

    q: queue.Queue[str] = queue.Queue()
    threading.Thread(
        target=reader_thread, args=(proc.stdout, "stdout", q), daemon=True
    ).start()
    threading.Thread(
        target=reader_thread, args=(proc.stderr, "stderr", q), daemon=True
    ).start()

    batch: list[str] = []
    last_push = 0.0
    last_beat = 0.0
    push_lines(cfg, [f"[bridge] Connected. cwd={bot_dir} · {cmd}"])

    try:
        while True:
            now = time.time()
            try:
                while True:
                    batch.append(q.get_nowait())
            except queue.Empty:
                pass

            if batch and (len(batch) >= 20 or now - last_push >= 0.6):
                ok = push_lines(cfg, batch)
                if not ok:
                    print("[bridge] Push failed (will retry).", file=sys.stderr)
                batch.clear()
                last_push = now

            if now - last_beat >= 8.0:
                heartbeat(cfg)
                last_beat = now

            code = proc.poll()
            if code is not None:
                # drain remaining
                time.sleep(0.2)
                try:
                    while True:
                        batch.append(q.get_nowait())
                except queue.Empty:
                    pass
                if batch:
                    push_lines(cfg, batch)
                push_lines(
                    cfg,
                    [f"[bridge] Process exited with code {code}."],
                )
                return code

            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n[bridge] Stopping…")
        try:
            proc.terminate()
        except Exception:
            pass
        push_lines(cfg, ["[bridge] Bridge stopped by user."])
        return 130


def main() -> int:
    parser = argparse.ArgumentParser(description="Beacon Console Bridge")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Re-run setup prompts even if config exists",
    )
    parser.add_argument(
        "--cmd",
        dest="command",
        default=None,
        help='Command to run inside the smmod folder, e.g. "py smmod.py"',
    )
    parser.add_argument(
        "--bot-dir",
        default=None,
        help=r'Folder that contains smmod.py, e.g. "C:\bots\smmod"',
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Vercel website URL",
    )
    parser.add_argument("--user", default=None, help="Console username")
    parser.add_argument(
        "--password",
        default=None,
        help="Console password (prefer prompt / config file)",
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="Only claim/login, do not start the bot",
    )
    args = parser.parse_args()

    cfg = load_config()
    need_setup = (
        args.setup
        or not cfg.get("base_url")
        or not cfg.get("username")
        or not cfg.get("password")
        or not cfg.get("bot_dir")
    )

    if need_setup and not (args.url and args.user and args.password):
        cfg = prompt_setup(cfg)
    else:
        if args.url:
            cfg["base_url"] = normalize_base(args.url)
        if args.user:
            cfg["username"] = args.user
        if args.password:
            cfg["password"] = args.password
        if args.command:
            cfg["command"] = args.command
        if args.bot_dir:
            resolved = resolve_bot_dir(args.bot_dir)
            if resolved:
                cfg["bot_dir"] = str(resolved)
        cfg.setdefault("command", DEFAULT_CMD)
        cfg.setdefault("bot_label", "smmod")
        if not cfg.get("bot_dir"):
            detected = find_smmod_dir()
            if detected:
                cfg["bot_dir"] = str(detected)
        save_config(cfg)

    if args.command:
        cfg["command"] = args.command
        save_config(cfg)
    if args.bot_dir:
        resolved = resolve_bot_dir(args.bot_dir)
        if resolved:
            cfg["bot_dir"] = str(resolved)
            save_config(cfg)

    claim(cfg)

    if args.no_run:
        print("[bridge] Claimed only (--no-run).")
        return 0

    return run_command(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
