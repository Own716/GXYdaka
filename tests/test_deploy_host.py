import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import deploy_host


class DeployHostTests(unittest.TestCase):
    def test_migration_hash_ignores_pycache_but_tracks_source_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            migrations = root / "server" / "migrations"
            migrations.mkdir(parents=True)
            source = migrations / "versions" / "001.py"
            source.parent.mkdir()
            source.write_bytes(b"revision = 'one'\n")
            expected = deploy_host.migration_hash(root)
            cache = migrations / "versions" / "__pycache__"
            cache.mkdir()
            (cache / "001.cpython-311.pyc").write_bytes(b"ignored")
            self.assertEqual(expected, deploy_host.migration_hash(root))
            source.write_bytes(b"revision = 'two'\n")
            self.assertNotEqual(expected, deploy_host.migration_hash(root))

    def test_atomic_symlink_replaces_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, second = root / "release-a", root / "release-b"
            first.mkdir()
            second.mkdir()
            current = root / "current"
            deploy_host.atomic_symlink(first, current)
            self.assertEqual(first, current.resolve())
            deploy_host.atomic_symlink(second, current)
            self.assertTrue(current.is_symlink())
            self.assertEqual(second, current.resolve())
            self.assertEqual(["current"], [p.name for p in root.iterdir() if p.name == "current"])

    def test_health_requires_both_boolean_readiness_fields(self):
        class Response:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.body).encode()

        def healthy_opener(_url, timeout):
            self.assertEqual(timeout, 3)
            return Response({"ok": True, "background_ready": True})

        self.assertTrue(deploy_host.check_health(("http://api/readyz", "http://worker/readyz"), 0, healthy_opener))
        self.assertFalse(deploy_host.check_health(
            ("http://api/readyz",), 0,
            lambda *_args, **_kwargs: Response({"ok": True, "background_ready": False}),
        ))

    def test_status_schema_and_deployed_sha_skip(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "base"
            base.mkdir()
            status = {"attempt": "a" * 40, "deployed": "a" * 40, "previous": "/legacy", "error": None}
            (base / "status.json").write_text(json.dumps(status), encoding="utf-8")
            config = dict(deploy_host.DEFAULTS)
            config.update(base_dir=str(base), legacy_dir=str(Path(temp) / "legacy"))
            with patch.object(deploy_host, "fetch_sha", return_value="a" * 40):
                result = deploy_host.Deployer(config).deploy()
            self.assertEqual("skipped", result)
            self.assertEqual({"attempt", "deployed", "previous", "error"}, set(deploy_host.read_status(base / "status.json")))

    def test_failed_sha_is_skipped_unless_retry_is_requested(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "base"
            base.mkdir()
            sha = "b" * 40
            status = {"attempt": sha, "deployed": "a" * 40, "previous": "/legacy", "error": "previous validation failed"}
            (base / "status.json").write_text(json.dumps(status), encoding="utf-8")
            config = dict(deploy_host.DEFAULTS)
            config.update(base_dir=str(base), legacy_dir=str(Path(temp) / "legacy"))
            with patch.object(deploy_host, "fetch_sha", return_value=sha):
                self.assertEqual("skipped", deploy_host.Deployer(config).deploy())
                # --retry proceeds past the skip guard and then predictably fails
                # at the absent archive/configuration without network or systemd.
                with self.assertRaises(deploy_host.DeployError):
                    deploy_host.Deployer(config, retry=True).deploy()
            self.assertEqual(sha, deploy_host.read_status(base / "status.json")["attempt"])

    def test_fetch_sha_explicitly_updates_branch_ref_in_bare_mirror(self):
        with tempfile.TemporaryDirectory() as temp:
            mirror = Path(temp) / "source.git"
            mirror.mkdir()
            (mirror / "HEAD").touch()
            sha = "c" * 40
            config = dict(deploy_host.DEFAULTS, branch="release/test")

            def run(args, **_kwargs):
                if args[4] == "fetch":
                    return None
                return type("Result", (), {"stdout": (sha + "\n").encode()})()

            with patch.object(deploy_host, "run_checked", side_effect=run) as mocked:
                self.assertEqual(sha, deploy_host.fetch_sha(config, mirror))
            fetch_command = mocked.call_args_list[0].args[0]
            self.assertEqual("+refs/heads/release/test:refs/heads/release/test", fetch_command[-1])

    def test_validation_logs_output_and_removes_production_env_link(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, release = root / "base", root / "release" / ("d" * 40)
            base.mkdir()
            (release / "web").mkdir(parents=True)
            runtime_env = root / "production.env"
            runtime_env.write_text("SECRET=must-not-be-read\n", encoding="utf-8")
            (release / ".env").symlink_to(runtime_env)
            test_env = root / "test-env.json"
            test_env.write_text(json.dumps({"DATABASE_URL": "sqlite:///isolated.db"}), encoding="utf-8")
            config = dict(deploy_host.DEFAULTS, base_dir=str(base), runtime_env_file=str(runtime_env), test_env_file=str(test_env))

            def run(_args, *, stdout, stderr, **_kwargs):
                self.assertFalse((release / ".env").exists())
                self.assertFalse((release / ".env").is_symlink())
                self.assertIs(stdout, stderr)
                stdout.write(b"captured stdout\n")
                stderr.write(b"captured stderr\n")

            with patch.object(deploy_host, "run_checked", side_effect=run) as mocked:
                deploy_host.validate_release(release, root / "python", config)
            self.assertEqual(6, mocked.call_count)
            log_path = base / "logs" / f"{release.name}.validation.log"
            self.assertIn(b"captured stdout", log_path.read_bytes())
            self.assertIn(b"captured stderr", log_path.read_bytes())
            self.assertEqual(0o700, (base / "logs").stat().st_mode & 0o777)
            self.assertEqual(0o600, log_path.stat().st_mode & 0o777)

    def test_runtime_images_persist_across_releases_and_idempotent_linking(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            legacy = root / "legacy"
            images = legacy / "server" / "images"
            images.mkdir(parents=True)
            photo = images / "existing.jpg"
            photo.write_bytes(b"existing user photo")
            runtime_env = root / "production.env"
            runtime_env.touch()
            config = dict(deploy_host.DEFAULTS, legacy_dir=str(legacy), runtime_env_file=str(runtime_env))
            for name in ("release-a", "release-b"):
                release = root / name
                (release / "server" / "images").mkdir(parents=True)
                deploy_host.install_runtime_links(release, config)
                deploy_host.install_runtime_links(release, config)
                self.assertTrue((release / "server" / "images").is_symlink())
                self.assertEqual(images.resolve(), (release / "server" / "images").resolve())
                self.assertEqual(b"existing user photo", photo.read_bytes())

    def test_runtime_images_never_overwrite_populated_candidate_or_wrong_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release = root / "release"
            images = release / "server" / "images"
            images.mkdir(parents=True)
            photo = images / "do-not-delete.jpg"
            photo.write_bytes(b"must survive")
            runtime_env = root / "production.env"
            runtime_env.touch()
            config = dict(deploy_host.DEFAULTS, legacy_dir=str(root / "legacy"), runtime_env_file=str(runtime_env))
            with self.assertRaisesRegex(deploy_host.DeployError, "refusing replacement"):
                deploy_host.install_runtime_links(release, config)
            self.assertEqual(b"must survive", photo.read_bytes())
            photo.unlink()
            images.rmdir()
            other = root / "other"
            other.mkdir()
            images.symlink_to(other)
            with self.assertRaisesRegex(deploy_host.DeployError, "somewhere unexpected"):
                deploy_host.install_runtime_links(release, config)
            self.assertEqual(other, images.resolve())

    def test_validation_detaches_production_images_before_candidate_tests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release = root / "release"
            (release / "web").mkdir(parents=True)
            (release / "server").mkdir()
            shared = root / "legacy" / "server" / "images"
            shared.mkdir(parents=True)
            photo = shared / "private.jpg"
            photo.write_bytes(b"private photo")
            link = release / "server" / "images"
            link.symlink_to(shared)
            test_env = root / "test-env.json"
            test_env.write_text(json.dumps({"DATABASE_URL": "mysql+pymysql://test:unused@127.0.0.1:1/test"}))
            config = dict(deploy_host.DEFAULTS, base_dir=str(root / "base"), legacy_dir=str(root / "legacy"), test_env_file=str(test_env))

            def check(_args, **_kwargs):
                self.assertFalse(link.is_symlink())
                self.assertFalse(link.exists())

            with patch.object(deploy_host, "run_checked", side_effect=check) as run:
                deploy_host.validate_release(release, root / "python", config)
            self.assertEqual(6, run.call_count)
            self.assertEqual(b"private photo", photo.read_bytes())

    def test_validation_rejects_unexpected_env_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release = root / "release"
            release.mkdir()
            (release / ".env").write_text("DATABASE_URL=unexpected\n", encoding="utf-8")
            config = dict(deploy_host.DEFAULTS, runtime_env_file=str(root / "production.env"))
            with patch.object(deploy_host, "run_checked") as run:
                with self.assertRaisesRegex(deploy_host.DeployError, "unexpected .env"):
                    deploy_host.validate_release(release, root / "python", config)
            run.assert_not_called()

    def test_failed_new_dependency_install_removes_incomplete_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release, base, legacy = root / "release", root / "base", root / "legacy"
            requirements = release / "server" / "requirements.txt"
            requirements.parent.mkdir(parents=True)
            requirements.write_text("example-package==1\n", encoding="utf-8")
            base.mkdir()
            env_path = base / "venvs" / deploy_host.sha256_file(requirements)

            def run(args, **_kwargs):
                if args[1:3] == ["-m", "venv"]:
                    (env_path / "bin").mkdir(parents=True)
                    (env_path / "bin" / "python").touch()
                    return None
                raise deploy_host.DeployError("simulated package install failure")

            with patch.object(deploy_host, "run_checked", side_effect=run):
                with self.assertRaisesRegex(deploy_host.DeployError, "simulated"):
                    deploy_host.ensure_dependency_env(release, base, legacy)
            self.assertFalse(env_path.exists())

    def test_failed_new_release_rolls_back_and_reports_rollback_health_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "base"
            old, new = base / "releases" / ("a" * 40), base / "releases" / ("b" * 40)
            old.mkdir(parents=True)
            new.mkdir()
            current = base / "current"
            current.symlink_to(old)
            config = dict(deploy_host.DEFAULTS, base_dir=str(base), legacy_dir=str(root / "legacy"))
            with patch.object(deploy_host, "fetch_sha", return_value="b" * 40), \
                 patch.object(deploy_host, "extract_release"), \
                 patch.object(deploy_host, "migration_hash", return_value="same"), \
                 patch.object(deploy_host, "ensure_dependency_env", return_value=root / "python"), \
                 patch.object(deploy_host, "validate_release"), \
                 patch.object(deploy_host, "install_runtime_links"), \
                 patch.object(deploy_host, "production_env", return_value={"DATABASE_URL": "test"}), \
                 patch.object(deploy_host, "create_database_backup"), \
                 patch.object(deploy_host, "stop_services") as stop, \
                 patch.object(deploy_host, "restart_services") as restart, \
                 patch.object(deploy_host, "check_health", side_effect=[False, False]) as health:
                with self.assertRaisesRegex(deploy_host.DeployError, "new release failed"):
                    deploy_host.Deployer(config).deploy()
            self.assertEqual(old.resolve(), current.resolve())
            self.assertEqual(2, health.call_count)
            self.assertEqual(2, restart.call_count)
            self.assertEqual(2, stop.call_count)
            status = deploy_host.read_status(base / "status.json")
            self.assertIn("rollback release failed readiness checks", status["error"])


if __name__ == "__main__":
    unittest.main()
