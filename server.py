"""
HA Config MCP Server — Home Assistant Addon
Transport: SSE (HTTP) na porcie 8765
Claude Desktop łączy się przez URL zamiast SSH/stdio
"""

import os
import difflib
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

# ── konfiguracja ────────────────────────────────────────────────────────────
CONFIG_DIR  = Path(os.environ.get("HA_CONFIG_DIR", "/config"))
GIT_REMOTE  = os.environ.get("GIT_REMOTE", "origin")
GIT_BRANCH  = os.environ.get("GIT_BRANCH", "main")
HA_TOKEN    = os.environ.get("HA_TOKEN", "")
HA_URL      = os.environ.get("HA_URL", "http://supervisor/core")
PORT        = int(os.environ.get("MCP_PORT", "8765"))

ALLOWED_EXTENSIONS = {".yaml", ".yml", ".json", ".toml", ".txt", ".conf", ".cfg"}
BLOCKED_PATHS      = {".storage", ".cloud", ".HA_VERSION", "secret", "secrets.yaml"}

mcp = FastMCP("ha-config-mcp", port=PORT)

# ── helpers ──────────────────────────────────────────────────────────────────

def _resolve(path: str) -> Path:
    p = (CONFIG_DIR / path).resolve()
    p.relative_to(CONFIG_DIR.resolve())
    for blocked in BLOCKED_PATHS:
        if blocked in p.parts or p.name == blocked:
            raise ValueError(f"Ścieżka zablokowana: {path}")
    if p.suffix and p.suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Niedozwolone rozszerzenie: {p.suffix}")
    return p


def _git(*args: str) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args], cwd=CONFIG_DIR,
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _ensure_git() -> bool:
    code, _, _ = _git("rev-parse", "--is-inside-work-tree")
    return code == 0


def _make_diff(old: str, new: str, filename: str) -> str:
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    )
    return "".join(diff) or "(brak zmian)"


def _ha_reload(target: str = "all") -> dict:
    import urllib.request
    endpoints = {
        "templates":   "/api/services/template/reload",
        "automations": "/api/services/automation/reload",
        "scripts":     "/api/services/script/reload",
        "all":         "/api/services/homeassistant/reload_all",
    }
    url = HA_URL.rstrip("/") + endpoints.get(target, endpoints["all"])
    req = urllib.request.Request(
        url, data=b"{}",
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"status": resp.status, "ok": True}
    except Exception as e:
        return {"status": None, "ok": False, "error": str(e)}


# ── narzędzia MCP ─────────────────────────────────────────────────────────────

@mcp.tool()
def list_config_files(subdir: str = "") -> dict:
    """Wylistuj pliki konfiguracyjne HA."""
    base = (CONFIG_DIR / subdir).resolve()
    base.relative_to(CONFIG_DIR.resolve())
    entries = []
    for item in sorted(base.iterdir()):
        if item.name.startswith("."):
            continue
        if any(b in item.parts or item.name == b for b in BLOCKED_PATHS):
            continue
        entries.append({
            "name": item.name,
            "type": "dir" if item.is_dir() else "file",
            "size": item.stat().st_size if item.is_file() else None,
            "path": str(item.relative_to(CONFIG_DIR)),
        })
    return {"base": str(base.relative_to(CONFIG_DIR)), "entries": entries}


@mcp.tool()
def read_config_file(path: str) -> dict:
    """Odczytaj plik konfiguracyjny HA."""
    p = _resolve(path)
    if not p.exists():
        return {"error": f"Plik nie istnieje: {path}"}
    content = p.read_text(encoding="utf-8")
    return {"path": path, "content": content, "lines": content.count("\n") + 1}


@mcp.tool()
def propose_edit(path: str, new_content: str) -> dict:
    """
    Zaproponuj zmianę pliku — pokaż diff ale NIE zapisuj.
    Zawsze wywołuj to przed write_config_file i czekaj na zatwierdzenie użytkownika.
    """
    p = _resolve(path)
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    diff = _make_diff(old, new_content, path)
    old_lines = old.splitlines()
    new_lines = new_content.splitlines()
    added   = sum(1 for l in difflib.ndiff(old_lines, new_lines) if l.startswith("+ "))
    removed = sum(1 for l in difflib.ndiff(old_lines, new_lines) if l.startswith("- "))
    return {
        "path": path,
        "diff": diff,
        "stats": {"lines_added": added, "lines_removed": removed},
        "instruction": "Pokaż diff użytkownikowi i CZEKAJ na zatwierdzenie. Wywołaj write_config_file dopiero gdy użytkownik powie OK.",
    }


@mcp.tool()
def write_config_file(
    path: str,
    new_content: str,
    commit_message: Optional[str] = None,
    reload_target: Optional[str] = None,
) -> dict:
    """
    Zapisz plik, zrób commit i push do GitHub.
    Wywołuj TYLKO po jawnym zatwierdzeniu przez użytkownika.
    reload_target: 'templates' | 'automations' | 'scripts' | 'all' | None
    """
    p = _resolve(path)
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    if old == new_content:
        return {"status": "no_change"}

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new_content, encoding="utf-8")
    result: dict = {"status": "saved", "path": path}

    if _ensure_git():
        ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = commit_message or f"chore(config): update {path} [{ts}]"
        _git("add", str(p.relative_to(CONFIG_DIR)))
        code, stdout, stderr = _git("commit", "-m", msg)
        if code == 0:
            _, commit_hash, _ = _git("rev-parse", "--short", "HEAD")
            result["git"] = {"committed": True, "hash": commit_hash, "message": msg}
            push_code, _, push_err = _git("push", GIT_REMOTE, GIT_BRANCH)
            result["git"]["pushed"] = push_code == 0
            if push_code != 0:
                result["git"]["push_error"] = push_err
        else:
            result["git"] = {"committed": False, "error": stderr or stdout}
    else:
        result["git"] = {"committed": False, "error": "Brak repo Git w /config"}

    if reload_target:
        result["ha_reload"] = _ha_reload(reload_target)

    return result


@mcp.tool()
def git_log(limit: int = 10) -> dict:
    """Historia commitów konfiguracji HA."""
    if not _ensure_git():
        return {"error": "Brak repo Git"}
    _, output, _ = _git("log", f"-{limit}", "--pretty=format:%H|%h|%ai|%s", "--", ".")
    commits = []
    for line in (output.splitlines() if output else []):
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({"hash": parts[0], "short": parts[1], "date": parts[2], "message": parts[3]})
    return {"commits": commits}


@mcp.tool()
def git_diff_commit(commit_hash: str) -> dict:
    """Diff dla konkretnego commita."""
    if not _ensure_git():
        return {"error": "Brak repo Git"}
    _, full_diff, _ = _git("show", commit_hash)
    return {"commit": commit_hash, "diff": full_diff}


@mcp.tool()
def reload_ha(target: str = "all") -> dict:
    """Przeładuj konfigurację HA bez restartu. target: templates|automations|scripts|all"""
    return _ha_reload(target)


if __name__ == "__main__":
    import asyncio
    print(f"Starting HA Config MCP on port {PORT} (SSE transport)...")
    mcp.run(transport="sse")
