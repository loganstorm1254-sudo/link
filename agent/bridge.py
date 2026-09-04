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
import atexit
import json
import os
import queue
import shutil
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
# Config next to the .exe pack root when running from BeaconConsoleBridge-Windows
_PACK_ROOT = BASE_DIR.parent if (BASE_DIR.parent / "python").is_dir() else BASE_DIR
CONFIG_PATH = _PACK_ROOT / "bridge_config.json"
DEFAULT_CMD = "smmod.py"  # resolved to: <system-python> -u smmod.py


def pause_before_close(msg: str = "") -> None:
    """Keep the window open so double-click launches show errors."""
    if msg:
        print(msg)
    try:
        input("\nPress Enter to close…")
    except Exception:
        time.sleep(12)


def fix_windows_path() -> None:
    """
    Double-clicking the .exe often has a tiny PATH (no `py` / `python`).
    Merge the real User + Machine PATH from the registry.
    """
    if os.name != "nt":
        return
    try:
        import winreg

        chunks: list[str] = []
        for root, sub in (
            (winreg.HKEY_CURRENT_USER, r"Environment"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            ),
        ):
            try:
                with winreg.OpenKey(root, sub) as key:
                    val, _ = winreg.QueryValueEx(key, "Path")
                    if val:
                        chunks.append(str(val))
            except OSError:
                pass
        current = os.environ.get("PATH", "")
        merged = os.pathsep.join([*chunks, current])
        # Expand %VARS%
        os.environ["PATH"] = os.path.expandvars(merged)
    except Exception:
        pass


def iter_common_python_exes() -> list[str]:
    homes = [
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        r"C:\\",
    ]
    versions = ["314", "313", "312", "311", "310", "39", "38"]
    found: list[str] = []
    for home in homes:
        if not home:
            continue
        for ver in versions:
            candidates = [
                Path(home) / "Programs" / "Python" / f"Python{ver}" / "python.exe",
                Path(home) / f"Python{ver}" / "python.exe",
                Path(home) / "Python" / f"Python{ver}" / "python.exe",
            ]
            for c in candidates:
                try:
                    if c.is_file():
                        found.append(str(c.resolve()))
                except Exception:
                    pass
    # py.exe launcher locations
    for c in (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "py.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs"
        / "Python"
        / "Launcher"
        / "py.exe",
    ):
        try:
            if c.is_file():
                found.append(str(c.resolve()))
        except Exception:
            pass
    return found


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


def resolve_system_python() -> str | None:
    """
    Find the real Windows Python that has discord.py — NOT the embeddable
    interpreter that ships inside BeaconConsoleBridge.exe.
    Avoid bare `py` with pipes (launcher can spawn a child and break stdio).
    """
    fix_windows_path()
    candidates: list[str] = []

    # Ask the py launcher for the real executable path (no pipes to the bot)
    launchers = ["py", "python", "python3", *iter_common_python_exes()]
    # De-dupe while preserving order
    seen_l: set[str] = set()
    ordered: list[str] = []
    for item in launchers:
        key = item.lower()
        if key in seen_l:
            continue
        seen_l.add(key)
        ordered.append(item)

    for launcher in ordered:
        if launcher.lower().endswith("python.exe"):
            candidates.append(launcher)
            continue
        for args in (
            [launcher, "-3", "-c", "import sys; print(sys.executable)"],
            [launcher, "-c", "import sys; print(sys.executable)"],
        ):
            try:
                out = subprocess.check_output(
                    args,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt"
                    else 0,
                ).strip()
                if out and Path(out).is_file():
                    if "BeaconConsoleBridge" in out.replace("\\", "/"):
                        continue
                    if (_PACK_ROOT / "python").resolve() in Path(out).resolve().parents:
                        continue
                    candidates.append(out)
                    break
            except Exception:
                continue

    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    seen: set[str] = set()
    unique: list[str] = []
    for exe in candidates:
        try:
            key = str(Path(exe).resolve()).lower()
        except Exception:
            key = exe.lower()
        if key in seen:
            continue
        # Never use the pack's embeddable interpreter to run the bot
        if "beaconconsolebridge" in key.replace("\\", "/"):
            continue
        if str((_PACK_ROOT / "python").resolve()).lower() in key:
            continue
        seen.add(key)
        unique.append(exe)

    # Prefer one that can import discord
    for exe in unique:
        try:
            subprocess.check_output(
                [exe, "-c", "import discord; print('ok')"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=12,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt"
                else 0,
            )
            return exe
        except Exception:
            continue

    # Last resort: any resolved interpreter (bot may still fail on missing deps)
    return unique[0] if unique else None


def kill_pid_tree(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass
    else:
        try:
            os.kill(pid, 15)
        except Exception:
            pass


def kill_stale_smmod(bot_dir: Path, previous_pid: int | None = None) -> None:
    """Stop leftover smmod.py processes so Discord token isn't shared."""
    if previous_pid:
        print(f"[bridge] Stopping previous bot PID {previous_pid}…")
        kill_pid_tree(previous_pid)

    if os.name != "nt":
        return

    # Kill any python still running smmod.py (common after closing the bridge window)
    try:
        ps = (
            "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
            "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'smmod\\.py') } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def build_bot_argv(cmd: str, bot_dir: Path, python_exe: str | None) -> tuple[list[str] | str, bool]:
    """
    Returns (argv_or_cmdline, use_shell).
    Default smmod launch → real python -u smmod.py (no shell, no py launcher).
    """
    raw = (cmd or "").strip()
    lowered = raw.lower()

    # Treat common defaults as "run smmod.py properly"
    if (
        not raw
        or lowered in {"smmod.py", "py smmod.py", "python smmod.py", "python3 smmod.py", "py -u smmod.py"}
        or lowered.replace(" ", "") in {"pysmod.py", "python-usmod.py"}
    ):
        script = bot_dir / "smmod.py"
        if not script.is_file():
            raise FileNotFoundError(f"smmod.py not found in {bot_dir}")
        if not python_exe:
            raise RuntimeError(
                "Could not find a system Python with discord.py. "
                "Install Python from python.org and `pip install discord.py`, "
                "then re-run the bridge."
            )
        return [python_exe, "-u", str(script)], False

    # Custom command — still prefer shell for exe paths / complex cmds
    return raw, True


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
    if str(cmd).strip().lower() in {"py smmod.py", "python smmod.py", "python3 smmod.py"}:
        cmd = DEFAULT_CMD
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
    # Normalize old default so we use real python -u launch
    if cmd.strip().lower() in {"py smmod.py", "python smmod.py", "python3 smmod.py"}:
        cmd = DEFAULT_CMD

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
            "clearLogs": True,  # wipe site console on every bridge start
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
    print("[bridge] Console claimed on Vercel (old logs wiped).")
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


def heartbeat(cfg: dict[str, Any], bot_running: bool = False) -> None:
    http_json(
        "POST",
        f"{cfg['base_url']}/api/heartbeat",
        {
            "botLabel": cfg.get("bot_label") or "smmod",
            "botRunning": bool(bot_running),
        },
        token=cfg.get("agent_token") or None,
        timeout=10.0,
    )


def poll_remote_command(cfg: dict[str, Any]) -> str | None:
    """Pull one pending start/stop from the website (clears it server-side)."""
    status, data = http_json(
        "GET",
        f"{cfg['base_url']}/api/control",
        token=cfg.get("agent_token") or None,
        timeout=10.0,
    )
    if status == 401:
        claim(cfg)
        status, data = http_json(
            "GET",
            f"{cfg['base_url']}/api/control",
            token=cfg.get("agent_token") or None,
            timeout=10.0,
        )
    if status != 200:
        return None
    cmd = data.get("command")
    if not isinstance(cmd, dict):
        return None
    action = str(cmd.get("action") or "").lower()
    if action in {"start", "stop"}:
        return action
    return None


def remote_command_watcher(
    cfg: dict[str, Any],
    flag: dict[str, str | None],
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        try:
            action = poll_remote_command(cfg)
            if action:
                flag["action"] = action
                print(f"[bridge] Remote command received: {action}")
        except Exception:
            pass
        stop_event.wait(1.2)


def reader_thread(stream, out_q: queue.Queue[str]) -> None:
    try:
        for raw in iter(stream.readline, b""):
            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                text = str(raw)
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            if text.endswith("\n"):
                text = text[:-1]
            if text == "":
                continue
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


def run_one_bot(
    cfg: dict[str, Any],
    bot_dir: Path,
    argv: list[str] | str,
    use_shell: bool,
    display: str,
    remote_flag: dict[str, str | None],
    *,
    first_start: bool,
) -> str:
    """
    Run smmod once.
    Returns: "exited" | "stopped" (local Ctrl+C or remote stop)
    """
    if not first_start:
        prev = cfg.get("bot_pid")
        if prev:
            kill_pid_tree(int(prev))
        time.sleep(1.0)

    remote_flag["action"] = None

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "bufsize": 0,
        "cwd": str(bot_dir),
        "env": env,
        "shell": use_shell,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(argv, **popen_kwargs)
    cfg["bot_pid"] = proc.pid
    save_config(cfg)

    q: queue.Queue[str] = queue.Queue()
    threading.Thread(target=reader_thread, args=(proc.stdout, q), daemon=True).start()

    batch: list[str] = []
    last_push = 0.0
    last_beat = 0.0
    push_lines(
        cfg,
        [
            f"[bridge] Started smmod PID {proc.pid}",
            f"[bridge] cwd={bot_dir}",
            f"[bridge] {display}",
            "[bridge] Ctrl+C or website Stop = stop smmod. Website Start / type start = run again.",
        ],
    )
    print("[bridge] Running. Ctrl+C or website Stop = stop smmod only.\n")
    heartbeat(cfg, bot_running=True)

    reason = "exited"
    try:
        while True:
            # Remote stop from website
            if remote_flag.get("action") == "stop":
                remote_flag["action"] = None
                print("\n[bridge] Website STOP — stopping smmod…")
                kill_pid_tree(proc.pid)
                push_lines(cfg, ["[bridge] smmod stopped (website Stop)."])
                reason = "stopped"
                break

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

            if now - last_beat >= 5.0:
                heartbeat(cfg, bot_running=True)
                last_beat = now

            code = proc.poll()
            if code is not None:
                time.sleep(0.2)
                try:
                    while True:
                        batch.append(q.get_nowait())
                except queue.Empty:
                    pass
                if batch:
                    push_lines(cfg, batch)
                push_lines(cfg, [f"[bridge] smmod exited with code {code}."])
                reason = "exited"
                break

            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n[bridge] Ctrl+C — stopping smmod only…")
        kill_pid_tree(proc.pid)
        time.sleep(0.2)
        try:
            while True:
                batch.append(q.get_nowait())
        except queue.Empty:
            pass
        if batch:
            push_lines(cfg, batch)
        push_lines(cfg, ["[bridge] smmod stopped (Ctrl+C). Bridge still running."])
        reason = "stopped"
    finally:
        kill_pid_tree(proc.pid)
        try:
            if proc.poll() is None:
                proc.wait(timeout=3)
        except Exception:
            pass
        cfg["bot_pid"] = None
        try:
            save_config(cfg)
        except Exception:
            pass
        heartbeat(cfg, bot_running=False)

    return reason


def wait_for_restart_command(
    cfg: dict[str, Any],
    remote_flag: dict[str, str | None],
) -> str:
    """
    After smmod stops: Enter/start / website Start = run again.
    quit / Ctrl+C = leave bridge.
    """
    print()
    print("=" * 56)
    print("  smmod stopped.")
    print("  start / Enter  → run smmod again")
    print("  (or press Start on the website)")
    print("  quit           → exit bridge")
    print("=" * 56)
    heartbeat(cfg, bot_running=False)

    # Non-blocking-ish: poll remote + short timed input via thread
    line_q: queue.Queue[str] = queue.Queue()

    def _reader() -> None:
        try:
            line_q.put(input("[bridge] > "))
        except (KeyboardInterrupt, EOFError):
            line_q.put("__quit__")

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    while True:
        if remote_flag.get("action") == "start":
            remote_flag["action"] = None
            print("[bridge] Website START — launching smmod…")
            push_lines(cfg, ["[bridge] Restarting smmod (website Start)…"])
            return "start"
        if remote_flag.get("action") == "stop":
            # already stopped
            remote_flag["action"] = None

        try:
            line = line_q.get(timeout=0.4).strip().lower()
        except queue.Empty:
            heartbeat(cfg, bot_running=False)
            continue

        if line in {"__quit__"}:
            print("\n[bridge] Exiting bridge.")
            return "quit"
        if line in {"", "start", "s", "run", "r", "restart"}:
            return "start"
        if line in {"quit", "q", "exit", "stop"}:
            return "quit"
        print(f"[bridge] Unknown {line!r} — type start or quit.")
        t = threading.Thread(target=_reader, daemon=True)
        t.start()


def run_command(cfg: dict[str, Any]) -> int:
    """
    Keep the bridge alive. Ctrl+C / website Stop only kills smmod.
    Website Start or typing start runs it again.
    """
    cmd = str(cfg.get("command") or DEFAULT_CMD)
    bot_dir = resolve_bot_dir(cfg.get("bot_dir")) or find_smmod_dir() or Path.cwd()
    if not bot_dir.is_dir():
        print(f"[bridge] Bot folder not found: {bot_dir}")
        sys.exit(1)

    prev = cfg.get("bot_pid")
    prev_pid = int(prev) if prev else None
    kill_stale_smmod(bot_dir, prev_pid)
    time.sleep(1.5)

    print("[bridge] Locating system Python (with discord.py)…")
    python_exe = resolve_system_python()
    if python_exe:
        print(f"[bridge] Using Python: {python_exe}")
    else:
        print("[bridge] WARNING: no system Python found — trying raw command")

    try:
        argv, use_shell = build_bot_argv(cmd, bot_dir, python_exe)
    except Exception as e:
        print(f"[bridge] Cannot start bot: {e}")
        sys.exit(1)

    display = " ".join(argv) if isinstance(argv, list) else str(argv)
    print(f"[bridge] Bot folder: {bot_dir}")
    print(f"[bridge] Command: {display}")
    print(f"[bridge] Streaming to: {cfg['base_url']}")
    print("[bridge] Website Start/Stop + local Ctrl+C / start / quit\n")

    remote_flag: dict[str, str | None] = {"action": None}
    stop_watch = threading.Event()
    watcher = threading.Thread(
        target=remote_command_watcher,
        args=(cfg, remote_flag, stop_watch),
        daemon=True,
    )
    watcher.start()

    def _cleanup_atexit() -> None:
        stop_watch.set()
        pid = cfg.get("bot_pid")
        if pid:
            kill_pid_tree(int(pid))

    atexit.register(_cleanup_atexit)

    first = True
    try:
        while True:
            run_one_bot(
                cfg,
                bot_dir,
                argv,
                use_shell,
                display,
                remote_flag,
                first_start=first,
            )
            first = False
            action = wait_for_restart_command(cfg, remote_flag)
            if action == "quit":
                push_lines(cfg, ["[bridge] Bridge exited."])
                print("[bridge] Bye.")
                return 0
            print("[bridge] Starting smmod again…\n")
            push_lines(cfg, ["[bridge] Restarting smmod…"])
            time.sleep(1.0)
    finally:
        stop_watch.set()
        heartbeat(cfg, bot_running=False)


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
    import traceback

    fix_windows_path()
    code: int | None = 0
    try:
        code = main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        if code != 0:
            pause_before_close()
        raise SystemExit(code)
    except Exception:
        print("\n[bridge] CRASH:")
        traceback.print_exc()
        pause_before_close()
        raise SystemExit(1)

    if code not in (0, None):
        pause_before_close(f"[bridge] Exited with code {code}")
    raise SystemExit(code or 0)
