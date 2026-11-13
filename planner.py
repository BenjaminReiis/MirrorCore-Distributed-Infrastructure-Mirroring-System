"""Planejamento: compara o estado desejado com o estado atual de cada destino."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .config import TargetConfig
from .manifest import Entry, is_excluded, sha256_bytes
from .templating import TemplateError, render


@dataclass(frozen=True)
class Desired:
    """Um arquivo que deve existir no destino."""

    path: str
    sha256: str
    mode: int
    source: Path
    rendered: Optional[bytes] = None  # preenchido quando veio de um template

    def read(self) -> bytes:
        return self.rendered if self.rendered is not None else self.source.read_bytes()


@dataclass(frozen=True)
class Action:
    kind: str  # "create" | "update" | "delete"
    path: str


@dataclass
class Plan:
    target: str
    actions: List[Action] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        return not self.actions


def desired_state(
    source_root: Path,
    manifest: Dict[str, Entry],
    target: TargetConfig,
    template_suffix: str,
) -> Dict[str, Desired]:
    """Monta o estado desejado de um destino, renderizando templates com as variáveis dele."""
    variables = {"TARGET_NAME": target.name, **target.vars}
    result: Dict[str, Desired] = {}
    for rel, entry in manifest.items():
        src = source_root / rel
        if template_suffix and rel.endswith(template_suffix) and len(rel) > len(template_suffix):
            out_rel = rel[: -len(template_suffix)]
            if out_rel in manifest:
                raise TemplateError(f"conflito: '{rel}' e '{out_rel}' existem na origem")
            try:
                rendered = render(src.read_text(encoding="utf-8"), variables).encode("utf-8")
            except TemplateError as exc:
                raise TemplateError(f"{rel}: {exc}")
            result[out_rel] = Desired(out_rel, sha256_bytes(rendered), entry.mode, src, rendered)
        else:
            result[rel] = Desired(rel, entry.sha256, entry.mode, src)
    return result


def compute_plan(
    target: str,
    desired: Dict[str, Desired],
    current: Dict[str, str],
    exclude: List[str],
    delete_extraneous: bool,
) -> Plan:
    """`current` mapeia caminho -> sha256 do que existe hoje no destino."""
    actions: List[Action] = []
    for path in sorted(desired):
        have = current.get(path)
        if have is None:
            actions.append(Action("create", path))
        elif have != desired[path].sha256:
            actions.append(Action("update", path))
    if delete_extraneous:
        for path in sorted(current):
            if path not in desired and not is_excluded(path, exclude):
                actions.append(Action("delete", path))
    return Plan(target, actions)
