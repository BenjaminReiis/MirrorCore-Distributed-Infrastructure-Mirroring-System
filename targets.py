"""Backends de destino: local (sistema de arquivos) e ssh."""
from __future__ import annotations

import os
import posixpath
import shlex
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict

from .config import TargetConfig
from .manifest import build_manifest


class BackendError(Exception):
    """Falha ao operar em um destino."""


class Backend(ABC):
    @abstractmethod
    def scan(self) -> Dict[str, str]:
        """Devolve {caminho_relativo: sha256} do que existe no destino."""

    @abstractmethod
    def put(self, rel: str, data: bytes, mode: int) -> None:
        """Grava (cria ou substitui) um arquivo de forma atômica."""

    @abstractmethod
    def delete(self, rel: str) -> None:
        """Remove um arquivo (e diretórios que ficarem vazios)."""


class LocalBackend(Backend):
    def __init__(self, cfg: TargetConfig):
        self.root = Path(cfg.path)

    def _safe(self, rel: str) -> Path:
        root = self.root.resolve()
        dest = (root / rel).resolve()
        if dest != root and root not in dest.parents:
            raise BackendError(f"caminho fora do destino: {rel}")
        return dest

    def scan(self) -> Dict[str, str]:
        return {p: e.sha256 for p, e in build_manifest(self.root).items()}

    def put(self, rel: str, data: bytes, mode: int) -> None:
        dest = self._safe(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.mirrorcore-tmp")
        tmp.write_bytes(data)
        os.chmod(tmp, mode)
        os.replace(tmp, dest)

    def delete(self, rel: str) -> None:
        dest = self._safe(rel)
        dest.unlink()
        root = self.root.resolve()
        parent = dest.parent
        while parent != root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


class SSHBackend(Backend):
    """Opera em um servidor remoto via `ssh` (requer chave configurada; sha256sum no remoto)."""

    def __init__(self, cfg: TargetConfig):
        self.cfg = cfg
        self.root = cfg.path.rstrip("/") or "/"
        self.dest = f"{cfg.user}@{cfg.host}" if cfg.user else str(cfg.host)

    def _run(self, remote_cmd: str, data: bytes = None) -> bytes:
        cmd = [
            "ssh", "-p", str(self.cfg.port),
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            self.dest, remote_cmd,
        ]
        try:
            proc = subprocess.run(cmd, input=data, capture_output=True)
        except FileNotFoundError:
            raise BackendError("comando 'ssh' não encontrado")
        if proc.returncode != 0:
            msg = proc.stderr.decode(errors="replace").strip() or f"código {proc.returncode}"
            raise BackendError(f"ssh {self.cfg.host}: {msg}")
        return proc.stdout

    def scan(self) -> Dict[str, str]:
        q = shlex.quote(self.root)
        out = self._run(
            f"if [ -d {q} ]; then cd {q} && find . -type f -exec sha256sum {{}} +; fi"
        ).decode("utf-8", errors="replace")
        result: Dict[str, str] = {}
        for line in out.splitlines():
            if len(line) < 67 or line.startswith("\\"):
                continue
            path = line[66:]
            if path.startswith("./"):
                path = path[2:]
            result[path] = line[:64]
        return result

    def put(self, rel: str, data: bytes, mode: int) -> None:
        remote = posixpath.join(self.root, rel)
        tmp = posixpath.join(posixpath.dirname(remote), f".{posixpath.basename(remote)}.mirrorcore-tmp")
        q = shlex.quote
        self._run(
            f"mkdir -p {q(posixpath.dirname(remote))} && cat > {q(tmp)} "
            f"&& chmod {mode:o} {q(tmp)} && mv -f {q(tmp)} {q(remote)}",
            data,
        )

    def delete(self, rel: str) -> None:
        q = shlex.quote
        remote = posixpath.join(self.root, rel)
        cmd = f"rm -f {q(remote)}"
        reldir = posixpath.dirname(rel)
        if reldir:
            cmd += (
                f" && (cd {q(self.root)} && "
                f"rmdir -p --ignore-fail-on-non-empty {q(reldir)} 2>/dev/null || true)"
            )
        self._run(cmd)


def create_backend(cfg: TargetConfig) -> Backend:
    if cfg.type == "local":
        return LocalBackend(cfg)
    if cfg.type == "ssh":
        return SSHBackend(cfg)
    raise BackendError(f"tipo de destino desconhecido: {cfg.type}")
