import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mirrorcore.cli import main
from mirrorcore.config import ConfigError, parse_config
from mirrorcore.engine import Engine, EngineError
from mirrorcore.manifest import build_manifest, is_excluded
from mirrorcore.templating import TemplateError, render


def write(path: Path, content: str = "x", mode: int = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mode is not None:
        os.chmod(path, mode)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src = self.tmp / "infra"
        self.src.mkdir()

    def config(self, targets=None, **extra):
        raw = {
            "source": "infra",
            "state_dir": "state",
            "targets": targets
            or [
                {"name": "a", "type": "local", "path": "replicas/a", "vars": {"ENV": "dev"}},
                {"name": "b", "type": "local", "path": "replicas/b", "vars": {"ENV": "prod"}},
            ],
        }
        raw.update(extra)
        return parse_config(raw, self.tmp)


class TestHelpers(unittest.TestCase):
    def test_render(self):
        self.assertEqual(render("env={{ ENV }}", {"ENV": "x"}), "env=x")
        with self.assertRaises(TemplateError):
            render("{{FALTA}}", {})

    def test_exclude(self):
        self.assertTrue(is_excluded("a/b/c.log", ["*.log"]))
        self.assertTrue(is_excluded("node_modules/x/y.js", ["node_modules"]))
        self.assertFalse(is_excluded("src/app.py", ["*.log"]))


class TestConfig(Base):
    def test_validacoes(self):
        with self.assertRaises(ConfigError):
            parse_config({}, self.tmp)
        with self.assertRaises(ConfigError):
            parse_config({"source": "infra", "targets": []}, self.tmp)
        with self.assertRaises(ConfigError):
            self.config(targets=[{"name": "a", "type": "ftp", "path": "x"}])
        with self.assertRaises(ConfigError):
            self.config(targets=[{"name": "a", "type": "ssh", "path": "/x"}])
        with self.assertRaises(ConfigError):  # destino dentro da origem
            self.config(targets=[{"name": "a", "type": "local", "path": "infra/sub"}])
        with self.assertRaises(ConfigError):  # nomes duplicados
            self.config(targets=[
                {"name": "a", "type": "local", "path": "r/1"},
                {"name": "a", "type": "local", "path": "r/2"},
            ])


class TestEngine(Base):
    def test_sync_idempotente_e_templates(self):
        write(self.src / "web/nginx.conf", "listen 80;")
        write(self.src / "app.conf.tpl", "env={{ENV}} node={{TARGET_NAME}}")
        write(self.src / "run.sh", "#!/bin/sh", mode=0o755)
        cfg = self.config()
        engine = Engine(cfg)

        res = engine.run(apply=True)
        self.assertTrue(all(r.ok and r.applied == 3 for r in res))
        self.assertEqual((self.tmp / "replicas/a/app.conf").read_text(), "env=dev node=a")
        self.assertEqual((self.tmp / "replicas/b/app.conf").read_text(), "env=prod node=b")
        self.assertTrue(os.stat(self.tmp / "replicas/a/run.sh").st_mode & stat.S_IXUSR)
        self.assertFalse((self.tmp / "replicas/a/app.conf.tpl").exists())

        again = engine.run(apply=True)  # segunda vez: nada a fazer
        self.assertTrue(all(r.total == 0 for r in again))
        self.assertTrue((self.tmp / "state/state.json").exists())

    def test_drift_update_e_delete(self):
        write(self.src / "a.txt", "um")
        cfg = self.config(delete_extraneous=True, exclude=["*.keep"])
        engine = Engine(cfg)
        engine.run(apply=True)

        write(self.tmp / "replicas/a/a.txt", "alterado")   # divergência
        write(self.tmp / "replicas/a/extra/lixo.txt", "!")  # arquivo a mais
        write(self.tmp / "replicas/a/meu.keep", "protegido")

        plan = engine.run(apply=False)
        kinds = {(a.kind, a.path) for a in plan[0].plan.actions}
        self.assertEqual(kinds, {("update", "a.txt"), ("delete", "extra/lixo.txt")})
        self.assertEqual((self.tmp / "replicas/a/a.txt").read_text(), "alterado")  # plan não altera

        engine.run(apply=True)
        self.assertEqual((self.tmp / "replicas/a/a.txt").read_text(), "um")
        self.assertFalse((self.tmp / "replicas/a/extra").exists())
        self.assertTrue((self.tmp / "replicas/a/meu.keep").exists())

    def test_origem_vazia_nao_faz_nada(self):
        with self.assertRaises(EngineError):
            Engine(self.config()).run(apply=True)

    def test_falha_em_um_destino_nao_derruba_os_outros(self):
        write(self.src / "app.conf.tpl", "env={{ENV}}")
        cfg = self.config(targets=[
            {"name": "ok", "type": "local", "path": "replicas/ok", "vars": {"ENV": "x"}},
            {"name": "ruim", "type": "local", "path": "replicas/ruim"},  # falta ENV
        ])
        res = Engine(cfg).run(apply=True)
        self.assertTrue(res[0].ok)
        self.assertFalse(res[1].ok)
        self.assertIn("ENV", res[1].errors[0])


@unittest.skipUnless(shutil.which("sha256sum") and os.name == "posix", "requer sha256sum/posix")
class TestSSH(Base):
    def test_ssh_com_ssh_falso(self):
        fake = self.tmp / "bin"
        fake.mkdir()
        script = fake / "ssh"
        script.write_text('#!/bin/sh\nfor last; do :; done\nexec sh -c "$last"\n')
        os.chmod(script, 0o755)
        remote = self.tmp / "remoto"

        write(self.src / "a/b.txt", "conteudo")
        write(self.src / "t.conf.tpl", "n={{TARGET_NAME}}")
        cfg = self.config(targets=[
            {"name": "srv", "type": "ssh", "host": "h", "user": "u", "path": str(remote)}
        ], delete_extraneous=True)

        with mock.patch.dict(os.environ, {"PATH": f"{fake}:{os.environ['PATH']}"}):
            engine = Engine(cfg)
            res = engine.run(apply=True)
            self.assertTrue(res[0].ok, res[0].errors)
            self.assertEqual((remote / "a/b.txt").read_text(), "conteudo")
            self.assertEqual((remote / "t.conf").read_text(), "n=srv")
            self.assertEqual(engine.run(apply=False)[0].total, 0)

            write(remote / "sobra/x.txt", "!")
            res = engine.run(apply=True)
            self.assertTrue(res[0].ok, res[0].errors)
            self.assertFalse((remote / "sobra").exists())


class TestCLI(Base):
    def test_fluxo_completo(self):
        cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, cwd)
        self.assertEqual(main(["init"]), 0)
        self.assertEqual(main(["init"]), 1)           # já existe
        self.assertEqual(main(["drift"]), 1)          # réplicas ainda não existem
        self.assertEqual(main(["sync", "--dry-run"]), 0)
        self.assertFalse((self.tmp / "replicas").exists())
        self.assertEqual(main(["sync"]), 0)
        self.assertEqual(main(["drift"]), 0)
        self.assertEqual(main(["status"]), 0)
        self.assertEqual(main(["-c", "nao-existe.json", "plan"]), 2)


if __name__ == "__main__":
    unittest.main()
