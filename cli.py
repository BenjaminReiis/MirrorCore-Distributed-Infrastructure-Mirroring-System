"""Interface de linha de comando do MirrorCore."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import Config, ConfigError, load_config
from .engine import Engine, EngineError, TargetResult, load_state

log = logging.getLogger("mirrorcore")

SYMBOLS = {"create": "+", "update": "~", "delete": "-"}

EXAMPLE_CONFIG = {
    "source": "./infra",
    "exclude": [".git", "*.log", "__pycache__", "*.tmp"],
    "delete_extraneous": True,
    "workers": 4,
    "state_dir": ".mirrorcore",
    "interval": 60,
    "template_suffix": ".tpl",
    "targets": [
        {"name": "replica-a", "type": "local", "path": "./replicas/a", "vars": {"ENV": "staging"}},
        {"name": "replica-b", "type": "local", "path": "./replicas/b", "vars": {"ENV": "production"}},
    ],
}

EXAMPLE_TEMPLATE = """# Configuração gerada pelo MirrorCore
ambiente = {{ENV}}
replica  = {{TARGET_NAME}}
"""


def report(results: List[TargetResult], applied: bool, quiet_in_sync: bool = False) -> None:
    for r in results:
        if quiet_in_sync and r.ok and r.total == 0:
            continue
        if r.plan is None:
            status = "ERRO"
        elif applied:
            status = f"{r.applied}/{r.total} alteração(ões) aplicada(s)" if r.total else "em sincronia"
        elif r.total:
            status = f"{r.total} alteração(ões) pendente(s)"
        else:
            status = "em sincronia"
        print(f"[{r.target}] {status}")
        if r.plan:
            for a in r.plan.actions:
                print(f"  {SYMBOLS[a.kind]} {a.path}")
        for err in r.errors:
            print(f"  ! {err}")


def cmd_init(args) -> int:
    cfg_path = Path(args.config)
    if cfg_path.exists() and not args.force:
        print(f"erro: {cfg_path} já existe (use --force para sobrescrever)", file=sys.stderr)
        return 1
    cfg_path.write_text(json.dumps(EXAMPLE_CONFIG, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    infra = cfg_path.resolve().parent / "infra"
    infra.mkdir(exist_ok=True)
    sample = infra / "app.conf.tpl"
    if not sample.exists():
        sample.write_text(EXAMPLE_TEMPLATE, encoding="utf-8")
    print(f"criado: {cfg_path} e {infra / 'app.conf.tpl'}")
    print("próximo passo: mirrorcore plan   (depois: mirrorcore sync)")
    return 0


def cmd_plan(engine: Engine, args) -> int:
    results = engine.run(apply=False)
    report(results, applied=False)
    return 1 if any(not r.ok for r in results) else 0


def cmd_drift(engine: Engine, args) -> int:
    results = engine.run(apply=False)
    report(results, applied=False)
    drifted = any(r.total for r in results)
    return 1 if drifted or any(not r.ok for r in results) else 0


def cmd_sync(engine: Engine, args) -> int:
    if args.dry_run:
        return cmd_plan(engine, args)
    results = engine.run(apply=True)
    report(results, applied=True)
    return 1 if any(not r.ok for r in results) else 0


def cmd_status(config: Config) -> int:
    state = load_state(config)
    if not state:
        print("nenhuma sincronização registrada ainda (rode: mirrorcore sync)")
        return 0
    print(f"última sincronização: {state['timestamp']}")
    for name, info in state["targets"].items():
        flag = "em sincronia" if info["in_sync"] else "COM PENDÊNCIAS"
        print(f"[{name}] {flag} (aplicadas: {info['applied']}, pendentes: {info['pending']})")
        for err in info["errors"]:
            print(f"  ! {err}")
    return 0


def cmd_watch(engine: Engine, config: Config, args) -> int:
    interval = args.interval or config.interval
    print(f"observando: sincronizando a cada {interval}s (Ctrl+C para sair)")
    try:
        while True:
            try:
                report(engine.run(apply=True), applied=True, quiet_in_sync=True)
            except EngineError as exc:
                log.error("%s", exc)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nencerrado")
        return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mirrorcore",
        description="Espelhamento de infraestrutura e sincronização de ambientes replicados.",
    )
    p.add_argument("-c", "--config", default="mirrorcore.json", help="arquivo de configuração")
    p.add_argument("-v", "--verbose", action="store_true", help="logs detalhados")
    p.add_argument("--version", action="version", version=f"mirrorcore {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="cria configuração e exemplo")
    s.add_argument("--force", action="store_true", help="sobrescreve a configuração existente")
    sub.add_parser("plan", help="mostra o que mudaria, sem alterar nada")
    s = sub.add_parser("sync", help="aplica a sincronização nos destinos")
    s.add_argument("--dry-run", action="store_true", help="apenas mostra o plano")
    sub.add_parser("drift", help="detecta divergência (sai com código 1 se houver)")
    sub.add_parser("status", help="mostra o resultado da última sincronização")
    s = sub.add_parser("watch", help="sincroniza continuamente em intervalos")
    s.add_argument("--interval", type=int, help="segundos entre sincronizações")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        if args.command == "init":
            return cmd_init(args)
        config = load_config(args.config)
        engine = Engine(config)
        if args.command == "status":
            return cmd_status(config)
        if args.command == "plan":
            return cmd_plan(engine, args)
        if args.command == "drift":
            return cmd_drift(engine, args)
        if args.command == "sync":
            return cmd_sync(engine, args)
        if args.command == "watch":
            return cmd_watch(engine, config, args)
    except (ConfigError, EngineError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    return 0
