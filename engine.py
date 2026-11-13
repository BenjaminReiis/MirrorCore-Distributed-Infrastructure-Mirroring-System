"""Motor: calcula planos e aplica a sincronização em todos os destinos em paralelo."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .config import Config, TargetConfig
from .manifest import build_manifest
from .planner import Plan, compute_plan, desired_state
from .targets import Backend, create_backend

log = logging.getLogger("mirrorcore")


class EngineError(Exception):
    """Erro que impede a execução (ex.: origem vazia)."""


@dataclass
class TargetResult:
    target: str
    plan: Optional[Plan] = None
    applied: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def total(self) -> int:
        return len(self.plan.actions) if self.plan else 0

    @property
    def pending(self) -> int:
        return self.total - self.applied


class Engine:
    def __init__(
        self,
        config: Config,
        backend_factory: Callable[[TargetConfig], Backend] = create_backend,
    ):
        self.config = config
        self.backend_factory = backend_factory

    def run(self, apply: bool = False) -> List[TargetResult]:
        """Com apply=False apenas planeja (nada é alterado)."""
        manifest = build_manifest(self.config.source, self.config.exclude)
        if not manifest:
            raise EngineError(
                f"origem vazia ou inexistente: {self.config.source} "
                "(por segurança nada será feito)"
            )
        with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
            futures = [
                pool.submit(self._process, t, manifest, apply) for t in self.config.targets
            ]
            results = [f.result() for f in futures]
        if apply:
            self._save_state(results)
        return results

    def _process(self, tcfg: TargetConfig, manifest, apply: bool) -> TargetResult:
        res = TargetResult(tcfg.name)
        try:
            desired = desired_state(
                self.config.source, manifest, tcfg, self.config.template_suffix
            )
            backend = self.backend_factory(tcfg)
            current = backend.scan()
            res.plan = compute_plan(
                tcfg.name, desired, current,
                self.config.exclude, self.config.delete_extraneous,
            )
            if not apply:
                return res
            for action in res.plan.actions:
                try:
                    if action.kind == "delete":
                        backend.delete(action.path)
                    else:
                        d = desired[action.path]
                        backend.put(d.path, d.read(), d.mode)
                    res.applied += 1
                    log.debug("[%s] %s %s", tcfg.name, action.kind, action.path)
                except Exception as exc:  # um arquivo com falha não derruba os demais
                    res.errors.append(f"{action.kind} {action.path}: {exc}")
        except Exception as exc:
            res.errors.append(str(exc))
        return res

    def _save_state(self, results: List[TargetResult]) -> None:
        state = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "targets": {
                r.target: {
                    "in_sync": r.ok and r.pending == 0,
                    "applied": r.applied,
                    "pending": r.pending,
                    "errors": r.errors,
                }
                for r in results
            },
        }
        try:
            self.config.state_dir.mkdir(parents=True, exist_ok=True)
            path = self.config.state_dir / "state.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            log.warning("não foi possível salvar o estado: %s", exc)


def load_state(config: Config) -> Optional[Dict]:
    path = config.state_dir / "state.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
