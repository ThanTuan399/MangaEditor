"""Managed startup for a local Hy-MT2 llama.cpp server on Windows.

The GUI never waits for model download or inference server initialization.
A server started manually by the user is never terminated by this manager.
"""
from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

_LOG = logging.getLogger(__name__)
_DEFAULT_MODEL = "tencent/Hy-MT2-1.8B-GGUF:Q4_K_M"


def find_llama_server(root: str | Path | None = None) -> Path | None:
    """Find a WinGet portable install even when winget failed to create aliases."""
    executable = shutil.which("llama-server.exe") or shutil.which("llama-server")
    if executable and Path(executable).is_file():
        return Path(executable)

    root = Path(root) if root else None
    candidates = [
        root / "llama-server.exe" if root else None,
        root / "llama.cpp" / "llama-server.exe" if root else None,
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate

    for environment in ("LOCALAPPDATA", "ProgramFiles"):
        location = os.environ.get(environment)
        if not location:
            continue
        packages = Path(location) / "Microsoft" / "WinGet" / "Packages"
        if not packages.is_dir():
            continue
        for folder in sorted(
            packages.glob("ggml.llamacpp_*"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            for executable in folder.rglob("llama-server.exe"):
                if executable.is_file():
                    return executable
    return None


def local_server_port(api_base: str) -> int | None:
    """Accept only the local HTTP endpoint supported by the Hy-MT2 backend."""
    try:
        parsed = urlsplit(str(api_base).strip())
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path.rstrip("/") not in {"", "/v1"}
            or parsed.query
            or parsed.fragment
        ):
            return None
        port = parsed.port if parsed.port is not None else 80
        if not 1 <= port <= 65535:
            return None
        return port
    except (ValueError, TypeError):
        return None


def is_port_busy(port: int) -> bool:
    """Use TCP rather than /v1/models because model initialization may be ongoing."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


class LocalHyMT2ServerManager:
    """Launch the server once without freezing Qt; clean up only our own child."""

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root)
        self._lock = threading.Lock()
        self._starting: set[int] = set()
        self._owned: dict[int, subprocess.Popen] = {}
        self._stopping = False

    def ensure_async(self, config) -> bool:
        """Start when selected in Settings and automatic startup is enabled."""
        if sys.platform != "win32":
            return False
        app_config = getattr(config, "app", None)
        translator = getattr(config, "translator", None)
        if not getattr(app_config, "auto_start_hymt2", True):
            return False
        if str(getattr(translator, "translator", "")).strip() != "local_hymt2":
            return False
        address = getattr(translator, "hymt_api_base", "http://127.0.0.1:8080/v1")
        port = local_server_port(address)
        if port is None:
            _LOG.warning("Hy-MT2 auto-start skipped: invalid local API URL %r", address)
            return False

        with self._lock:
            running = self._owned.get(port)
            if self._stopping or port in self._starting:
                return False
            if running is not None and running.poll() is None:
                return False
            self._starting.add(port)

        worker = threading.Thread(
            name=f"hymt2-start-{port}",
            target=self._start_in_background,
            args=(port,),
            daemon=True,
        )
        worker.start()
        return True

    def _start_in_background(self, port: int) -> None:
        try:
            if is_port_busy(port):
                _LOG.info("Hy-MT2 port %s is already in use; reusing existing server", port)
                return
            executable = find_llama_server(self.root)
            if executable is None:
                _LOG.warning(
                    "Hy-MT2 auto-start unavailable: llama-server.exe not found. "
                    "Install with: winget install llama.cpp"
                )
                return
            if self._stopping:
                return

            log_dir = self.root / "result"
            log_dir.mkdir(parents=True, exist_ok=True)
            logfile = log_dir / "hymt2-server.log"
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            command = [
                str(executable),
                "-hf", _DEFAULT_MODEL,
                "--host", "127.0.0.1",
                "--port", str(port),
            ]
            with logfile.open("ab") as output:
                process = subprocess.Popen(
                    command,
                    cwd=str(self.root),
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                )
            with self._lock:
                if self._stopping:
                    process.terminate()
                    return
                self._owned[port] = process
            _LOG.info(
                "Hy-MT2 started in background (pid=%s, port=%s, log=%s)",
                process.pid, port, logfile,
            )
        except Exception:
            _LOG.exception("Could not start local Hy-MT2 server; MangaEditor remains usable")
        finally:
            with self._lock:
                self._starting.discard(port)

    def stop(self) -> None:
        """Stop servers launched by this instance only, not user-started servers."""
        with self._lock:
            self._stopping = True
            processes = list(self._owned.values())
            self._owned.clear()
        for process in processes:
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    _LOG.warning("Unable to terminate Hy-MT2 pid=%s", process.pid)
