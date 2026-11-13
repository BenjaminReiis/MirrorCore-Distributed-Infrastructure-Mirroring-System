"""Carregamento e validação da configuração (JSON)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


class ConfigError(Exception):
    """Configuração inválida."""


@dataclass
class TargetConfig:
    name: str
    type: str  # "local" ou "ssh"
    path: str
    host: Optional[str] = None
    user: Optional[str] = None
    port: int = 22
    vars: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    source: Path
    targets: List[TargetConfig]
    exclude: List[str] = field(default_factory=list)
    delete_extraneous: bool = False
    workers: int = 4
    state_dir: Path = Path(".mirrorcore")
    interval: int = 60
    template_suffix: str = ".tpl"


def _resolve(base: Path, value: str) -> Path:
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def load_config(path) -> Config:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"arquivo de configuração não encontrado: {path}")
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON inválido em {path}: {exc}")
    return parse_config(raw, base_dir=path.resolve().parent)


def parse_config(raw: Any, base_dir: Path) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("a configuração deve ser um objeto JSON")
    if "source" not in raw:
        raise ConfigError("campo obrigatório ausente: 'source'")

    source = _resolve(base_dir, raw["source"])
    targets_raw = raw.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        raise ConfigError("'targets' deve ser uma lista com ao menos um destino")

    targets: List[TargetConfig] = []
    names = set()
    for i, t in enumerate(targets_raw):
        if not isinstance(t, dict):
            raise ConfigError(f"targets[{i}] deve ser um objeto")
        for key in ("name", "type", "path"):
            if key not in t:
                raise ConfigError(f"targets[{i}]: campo obrigatório ausente: '{key}'")
        if t["type"] not in ("local", "ssh"):
            raise ConfigError(f"targets[{i}]: tipo inválido '{t['type']}' (use 'local' ou 'ssh')")
        if t["type"] == "ssh" and not t.get("host"):
            raise ConfigError(f"targets[{i}]: destino ssh exige 'host'")
        if t["name"] in names:
            raise ConfigError(f"nome de destino duplicado: '{t['name']}'")
        names.add(t["name"])

        path_value = t["path"]
        if t["type"] == "local":
            dest = _resolve(base_dir, path_value)
            if dest == source or source in dest.parents or dest in source.parents:
                raise ConfigError(
                    f"destino '{t['name']}' não pode ser igual, estar dentro ou conter a origem"
                )
            path_value = str(dest)

        targets.append(
            TargetConfig(
                name=t["name"],
                type=t["type"],
                path=path_value,
                host=t.get("host"),
                user=t.get("user"),
                port=int(t.get("port", 22)),
                vars=dict(t.get("vars", {})),
            )
        )

    workers = int(raw.get("workers", 4))
    if workers < 1:
        raise ConfigError("'workers' deve ser >= 1")
    interval = int(raw.get("interval", 60))
    if interval < 1:
        raise ConfigError("'interval' deve ser >= 1")

    state_dir = _resolve(base_dir, raw.get("state_dir", ".mirrorcore"))
    exclude = list(raw.get("exclude", []))
    try:  # nunca espelhar o próprio diretório de estado
        exclude.append(state_dir.relative_to(source).as_posix())
    except ValueError:
        pass

    return Config(
        source=source,
        targets=targets,
        exclude=exclude,
        delete_extraneous=bool(raw.get("delete_extraneous", False)),
        workers=workers,
        state_dir=state_dir,
        interval=interval,
        template_suffix=raw.get("template_suffix", ".tpl"),
    )
