import _bootstrap  # noqa: F401

import threading
from pathlib import Path
from types import SimpleNamespace

from utils import local_hymt2_autostart as local


def _config(translator="local_hymt2", enabled=True, url="http://127.0.0.1:8080/v1"):
    return SimpleNamespace(
        app=SimpleNamespace(auto_start_hymt2=enabled),
        translator=SimpleNamespace(translator=translator, hymt_api_base=url),
    )


def test_parse_only_local_server_address():
    assert local.local_server_port("http://127.0.0.1:8080/v1") == 8080
    assert local.local_server_port("http://localhost:8081") == 8081
    assert local.local_server_port("http://[::1]:8079/v1") == 8079
    assert local.local_server_port("http://127.0.0.1.evil.com:8080/v1") is None
    assert local.local_server_port("https://example.com:8080/v1") is None
    assert local.local_server_port("http://localhost:0/v1") is None
    assert local.local_server_port("http://localhost:8080/private") is None


def test_auto_start_only_if_enabled_and_selected(tmp_path, monkeypatch):
    monkeypatch.setattr(local.sys, "platform", "win32")
    manager = local.LocalHyMT2ServerManager(tmp_path)
    started = []
    done = threading.Event()

    def stub_start(port):
        started.append(port)
        done.set()

    monkeypatch.setattr(manager, "_start_in_background", stub_start)
    assert manager.ensure_async(_config("google_web")) is False
    assert manager.ensure_async(_config(enabled=False)) is False
    assert manager.ensure_async(_config(url="https://server.example/v1")) is False
    assert manager.ensure_async(_config()) is True
    assert done.wait(3)
    assert started == [8080]


def test_manager_does_not_spawn_if_port_is_in_use(tmp_path, monkeypatch):
    manager = local.LocalHyMT2ServerManager(tmp_path)
    monkeypatch.setattr(local, "is_port_busy", lambda port: True)
    monkeypatch.setattr(
        local,
        "find_llama_server",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not search")),
    )
    manager._start_in_background(8080)
    assert 8080 not in manager._owned


def test_manager_starts_hidden_server_and_stops_only_its_child(tmp_path, monkeypatch):
    executable = tmp_path / "llama-server.exe"
    executable.write_bytes(b"fake")
    monkeypatch.setattr(local, "find_llama_server", lambda *_: executable)
    monkeypatch.setattr(local, "is_port_busy", lambda *_: False)

    launches = []
    class Child:
        pid = 42
        killed = False
        def poll(self):
            return None
        def terminate(self):
            self.killed = True

    child = Child()
    def fake_popen(command, **kwargs):
        launches.append((command, kwargs))
        return child

    monkeypatch.setattr(local.subprocess, "Popen", fake_popen)
    manager = local.LocalHyMT2ServerManager(tmp_path)
    manager._start_in_background(8080)
    assert len(launches) == 1
    args, kwargs = launches[0]
    assert args[0] == str(executable)
    assert "--host" in args and "127.0.0.1" in args
    assert "--port" in args and "8080" in args
    assert kwargs["stdin"] == local.subprocess.DEVNULL
    assert (tmp_path / "result" / "hymt2-server.log").exists()
    assert 8080 in manager._owned
    manager.stop()
    assert child.killed
    assert manager._owned == {}


def test_winget_portable_executable_is_found(tmp_path, monkeypatch):
    install = tmp_path / "Microsoft" / "WinGet" / "Packages"
    directory = install / "ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe"
    directory.mkdir(parents=True)
    executable = directory / "llama-server.exe"
    executable.write_bytes(b"fake")
    monkeypatch.setattr(local.shutil, "which", lambda _name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    assert local.find_llama_server(tmp_path / "project") == executable
