"""Manifestos: retrato de uma árvore de arquivos (caminho -> SHA-256)."""
from __future__ import annotations

import fnmatch
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable

CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Entry:
    path: str
    sha256: str
    size: int
    mode: int


def is_excluded(rel: str, patterns: Iterable[str]) -> bool:
    """True se o caminho (ou qualquer parte dele) casa com algum padrão."""
    parts = rel.split("/")
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat):
            return True
        if any(fnmatch.fnmatch(part, pat) for part in parts):
            return True
    return False


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _join(a: str, b: str) -> str:
    return f"{a}/{b}" if a else b


def build_manifest(root: Path, exclude: Iterable[str] = ()) -> Dict[str, Entry]:
    """Percorre `root` e devolve {caminho_relativo: Entry}. Links simbólicos são ignorados."""
    patterns = list(exclude)
    result: Dict[str, Entry] = {}
    if not root.is_dir():
        return result
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = sorted(
            d for d in dirnames if not is_excluded(_join(rel_dir, d), patterns)
        )
        for name in sorted(filenames):
            rel = _join(rel_dir, name)
            full = Path(dirpath) / name
            if is_excluded(rel, patterns) or full.is_symlink():
                continue
            st = full.stat()
            result[rel] = Entry(rel, sha256_file(full), st.st_size, st.st_mode & 0o777)
    return result
