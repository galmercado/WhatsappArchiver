"""Deterministic fakes: ADB runner (rooted/unrooted/unauthorized...), scripted UI."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from waarchive.ingest.adb import ADBError, RunResult

SERIAL = "R58M123ABCD"


class FakeADBRunner:
    def __init__(
        self,
        *,
        devices: list[tuple[str, str]] | None = None,
        rooted: bool = False,
        fs: dict[str, bytes] | None = None,
        su_hangs: bool = False,
    ) -> None:
        self.devices = [(SERIAL, "device")] if devices is None else devices
        self.rooted, self.fs, self.su_hangs = rooted, dict(fs or {}), su_hangs
        self.log: list[list[str]] = []

    # -- helpers
    def _children(self, path: str) -> list[str] | None:
        prefix = path.rstrip("/") + "/"
        names = {k[len(prefix) :].split("/", 1)[0] for k in self.fs if k.startswith(prefix)}
        return sorted(names) if names else None

    def run(self, args: Sequence[str], *, timeout: float = 30.0) -> RunResult:
        a = list(args)
        self.log.append(a)
        if a == ["devices"]:
            body = "List of devices attached\n" + "".join(f"{s}\t{st}\n" for s, st in self.devices)
            return RunResult(0, body.encode())
        if a[:1] == ["-s"]:
            a = a[2:]
        if a[:1] == ["shell"]:
            cmd = a[1:]
            if cmd == ["su -c 'id'"]:
                if self.su_hangs:
                    raise ADBError("adb command timed out")
                if self.rooted:
                    return RunResult(0, b"uid=0(root) gid=0(root)\n")
                return RunResult(127, b"", b"/system/bin/sh: su: inaccessible or not found")
            if cmd[0] == "ls":
                kids = self._children(cmd[-1])
                return RunResult(0, "\n".join(kids).encode()) if kids is not None else RunResult(1)
        if a[:1] == ["pull"]:
            return self._pull(a[1], Path(a[2]))
        return RunResult(1, b"", b"unsupported in fake")

    def _pull(self, remote: str, local: Path) -> RunResult:
        if remote in self.fs:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(self.fs[remote])
            return RunResult(0)
        prefix = remote.rstrip("/") + "/"
        hits = {k: v for k, v in self.fs.items() if k.startswith(prefix)}
        if not hits:
            return RunResult(1)
        base = local / remote.rstrip("/").rsplit("/", 1)[-1]
        for k, v in hits.items():
            dest = base / k[len(prefix) :]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(v)
        return RunResult(0)

    def run_to_file(self, args: Sequence[str], dest: Path, *, timeout: float = 600.0) -> int:
        a = list(args)
        self.log.append(a)
        dest.write_bytes(b"")
        if a[2:3] == ["exec-out"] or a[:1] == ["-s"]:
            cmd = a[3]
            if self.rooted and cmd.startswith("su -c 'cat ") and cmd.endswith("'"):
                path = cmd[len("su -c 'cat ") : -1]
                if path in self.fs:
                    dest.write_bytes(self.fs[path])
                    return 0
        return 1


class ScriptedUI:
    def __init__(self, answers: list[str] | None = None, secrets: list[str] | None = None) -> None:
        self.answers, self.secrets = list(answers or []), list(secrets or [])
        self.said: list[str] = []
        self.alerts: list[str] = []

    def say(self, msg: str) -> None:
        self.said.append(msg)

    def alert(self, msg: str) -> None:
        self.alerts.append(msg)

    def ask(self, prompt: str) -> str:
        return self.answers.pop(0)

    def ask_secret(self, prompt: str) -> bytearray:
        return bytearray(self.secrets.pop(0).encode())
