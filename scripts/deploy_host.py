#!/usr/bin/env python3
"""Deterministic host deployment for the Gongxueyun systemd services.

This program intentionally performs no deployment unless invoked explicitly. It
uses only the public repository URL and never reads the production environment
until candidate tests have passed.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import unquote, urlsplit

LOG = logging.getLogger("deploy_host")
DEFAULTS = {
    "repo_url": "https://github.com/Own716/GXYdaka.git",
    "branch": "main",
    "base_dir": "/workspace/gxy-deploy",
    "runtime_env_file": "/workspace/gongxueyun/.env",
    "legacy_dir": "/workspace/gongxueyun",
    "test_env_file": "/workspace/gxy-deploy/test-env.json",
}
REPO_ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 900


class DeployError(RuntimeError):
    """An expected and safe-to-report deployment failure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migration_hash(root: Path) -> str:
    """Hash migration Python source names and bytes, excluding interpreter cache."""
    migration_root = root / "server" / "migrations"
    digest = hashlib.sha256()
    if not migration_root.exists():
        return digest.hexdigest()
    for path in sorted(migration_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(migration_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"attempt": None, "deployed": None, "previous": None, "error": None}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeployError("status.json is unreadable; inspect it before deploying") from exc
    return {key: value.get(key) for key in ("attempt", "deployed", "previous", "error")}


def atomic_symlink(target: Path, link: Path) -> None:
    """Atomically replace a symlink without following the existing link."""
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(f".{link.name}.{os.getpid()}.new")
    try:
        temporary.unlink(missing_ok=True)
        os.symlink(str(target), temporary)
        os.replace(temporary, link)
    finally:
        temporary.unlink(missing_ok=True)


def run_checked(args: list[str], *, cwd: Path | None = None,
                env: dict[str, str] | None = None, timeout: int = TIMEOUT,
                stdout: Any = subprocess.PIPE,
                stderr: Any = subprocess.PIPE) -> subprocess.CompletedProcess:
    """Run a child quietly; never include command output (which may be secret)."""
    try:
        result = subprocess.run(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=stdout, stderr=stderr, timeout=timeout,
                                check=False)
    except subprocess.TimeoutExpired as exc:
        raise DeployError(f"command timed out after {timeout}s: {args[0]}") from exc
    except OSError as exc:
        raise DeployError(f"could not run {args[0]}") from exc
    if result.returncode:
        raise DeployError(f"command failed ({result.returncode}): {args[0]}")
    return result


def clean_git_env() -> dict[str, str]:
    env = os.environ.copy()
    # Do not inherit git config injections, credential helpers, or askpass hooks.
    for key in list(env):
        if key.startswith("GIT_CONFIG") or key in {"GIT_ASKPASS", "SSH_ASKPASS"}:
            env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    return env


def safe_repo_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise DeployError("repo_url must be a public HTTPS URL without embedded credentials")
    return value


def fetch_sha(config: dict[str, str], mirror: Path) -> str:
    url = safe_repo_url(config["repo_url"])
    env = clean_git_env()
    mirror.parent.mkdir(parents=True, exist_ok=True)
    if not mirror.exists():
        run_checked(["git", "-c", "credential.helper=", "clone", "--bare", "--", url, str(mirror)], env=env)
    else:
        if not (mirror / "HEAD").exists():
            raise DeployError("mirror path exists but is not a bare git repository")
        branch = config["branch"]
        run_checked(["git", "-C", str(mirror), "-c", "credential.helper=", "fetch", "--prune", "origin",
                     f"+refs/heads/{branch}:refs/heads/{branch}"], env=env)
    result = run_checked(["git", "-C", str(mirror), "rev-parse", f"refs/heads/{config['branch']}^{{commit}}"], env=env)
    sha = result.stdout.decode("ascii", errors="strict").strip()
    if len(sha) != 40 or any(char not in "0123456789abcdef" for char in sha.lower()):
        raise DeployError("git returned an invalid commit SHA")
    return sha.lower()


def extract_release(mirror: Path, sha: str, destination: Path) -> None:
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{sha}.", dir=destination.parent))
    archive = temp / "source.tar"
    try:
        run_checked(["git", "-C", str(mirror), "archive", "--format=tar", "-o", str(archive), sha], timeout=TIMEOUT)
        root = temp / "tree"
        root.mkdir()
        with tarfile.open(archive, "r:") as tar:
            members = tar.getmembers()
            for member in members:
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts or not (member.isdir() or member.isfile()):
                    raise DeployError("release archive contains an unsafe file entry")
            tar.extractall(root, members=members)
        os.replace(root, destination)
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def ensure_dependency_env(release: Path, base: Path, legacy: Path) -> Path:
    requirements = release / "server" / "requirements.txt"
    if not requirements.is_file():
        raise DeployError("release is missing server/requirements.txt")
    digest = sha256_file(requirements)
    env_path = base / "venvs" / digest
    python = env_path / "bin" / "python"
    if not python.exists():
        legacy_requirements = legacy / "server" / "requirements.txt"
        legacy_python = legacy / ".venv" / "bin" / "python"
        if (legacy_requirements.is_file() and legacy_python.is_file()
                and legacy_requirements.read_bytes() == requirements.read_bytes()):
            env_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.symlink(str(legacy / ".venv"), env_path)
            except FileExistsError:
                if not python.exists():
                    raise DeployError("dependency virtual environment appeared incompletely")
        else:
            env_path.parent.mkdir(parents=True, exist_ok=True)
            newly_created = not env_path.exists() and not env_path.is_symlink()
            try:
                run_checked([sys.executable, "-m", "venv", str(env_path)])
                run_checked([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements)], timeout=TIMEOUT)
            except Exception:
                if newly_created:
                    shutil.rmtree(env_path, ignore_errors=True)
                raise
    if not python.exists():
        raise DeployError("dependency virtual environment is incomplete")
    release_venv = release / ".venv"
    if release_venv.exists() or release_venv.is_symlink():
        if not release_venv.is_symlink() or release_venv.resolve() != env_path.resolve():
            raise DeployError("release contains an unexpected .venv path")
    else:
        release_venv.symlink_to(env_path)
    return python


def test_environment(path: Path) -> dict[str, str]:
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeployError("test-env.json is missing or invalid") from exc
    if not isinstance(values, dict) or any(not isinstance(k, str) or not isinstance(v, (str, int, float, bool)) for k, v in values.items()):
        raise DeployError("test-env.json must contain a flat JSON object of environment values")
    env = {key: str(value) for key, value in values.items()}
    if not env.get("DATABASE_URL"):
        raise DeployError("test-env.json must define an isolated DATABASE_URL")
    safe = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp"), "LANG": "C.UTF-8"}
    safe.update(env)
    safe["APP_ENV"] = "test"
    return safe


def validate_release(release: Path, python: Path, config: dict[str, str]) -> None:
    env_link = release / ".env"
    if env_link.is_symlink():
        runtime_env = Path(config["runtime_env_file"])
        if env_link.resolve() != runtime_env.resolve():
            raise DeployError("release contains an unexpected .env path")
        env_link.unlink()
    elif env_link.exists():
        raise DeployError("release contains an unexpected .env path")

    # A retried candidate must not expose production photos during its tests.
    release_images = release / "server" / "images"
    if release_images.is_symlink():
        shared_images = Path(config["legacy_dir"]) / "server" / "images"
        if release_images.resolve() != shared_images.resolve():
            raise DeployError("release images symlink points somewhere unexpected")
        release_images.unlink()

    env = test_environment(Path(config["test_env_file"]))
    base = Path(config["base_dir"])
    logs = base / "logs"
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(logs, 0o700)
    log_path = logs / f"{release.name}.validation.log"
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb") as log:
        phases = [
            ("isolated database migration", [str(python), "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], release),
            ("Python unit tests", [str(python), "-m", "unittest", "discover", "-s", "tests", "-v"], release),
            ("quality gate", [str(python), "scripts/quality_gate.py"], release),
        ]
        web = release / "web"
        phases.extend([
            ("web dependency installation", ["npm", "ci", "--no-audit", "--no-fund"], web),
            ("web tests", ["npm", "test"], web),
            ("web production build", ["npm", "run", "build"], web),
        ])
        for description, command, cwd in phases:
            LOG.info("validating %s: %s", release.name, description)
            run_checked(command, cwd=cwd, env=env, stdout=log, stderr=log)


def production_env(runtime_env: Path, legacy: Path) -> dict[str, str]:
    python = legacy / ".venv" / "bin" / "python"
    if not python.is_file():
        raise DeployError("legacy virtualenv is required to read the production dotenv file")
    code = "import json,sys; from dotenv import dotenv_values; print(json.dumps({k:v for k,v in dotenv_values(sys.argv[1]).items() if v is not None}))"
    result = run_checked([str(python), "-c", code, str(runtime_env)], timeout=30)
    try:
        data = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeployError("legacy dotenv reader returned invalid data") from exc
    if not isinstance(data, dict):
        raise DeployError("production dotenv did not contain a key/value mapping")
    return {str(key): str(value) for key, value in data.items()}


def create_database_backup(base: Path, env: dict[str, str], legacy: Path) -> Path:
    raw_url = env.get("DATABASE_URL", "")
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql", "mariadb", "mariadb+pymysql"} or not parsed.hostname or not parsed.path.strip("/"):
        raise DeployError("production DATABASE_URL is not a supported MySQL URL")
    username, password = unquote(parsed.username or ""), unquote(parsed.password or "")
    database = unquote(parsed.path.lstrip("/"))
    if any(char in value for value in (username, password, parsed.hostname) for char in "\r\n"):
        raise DeployError("production MySQL URL contains an invalid connection field")
    backup_dir = base / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = backup_dir / f"{stamp}-{int(time.time_ns())}.sql"
    fd, option_path = tempfile.mkstemp(prefix=".mysqldump-", dir=backup_dir)
    os.fchmod(fd, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("[client]\n")
            stream.write(f"user={username}\npassword={password}\nhost={parsed.hostname}\n")
            if parsed.port:
                stream.write(f"port={parsed.port}\n")
            stream.write("default-character-set=utf8mb4\n")
            stream.flush()
            os.fsync(stream.fileno())
        out_fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            env2 = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(base)}
            run_checked(["mysqldump", f"--defaults-file={option_path}", "--single-transaction", "--no-tablespaces", "--set-gtid-purged=OFF", "--", database], env=env2, timeout=TIMEOUT, stdout=out_fd)
            os.fsync(out_fd)
        finally:
            os.close(out_fd)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    finally:
        Path(option_path).unlink(missing_ok=True)
    return backup


def install_runtime_links(release: Path, config: dict[str, str]) -> None:
    runtime_env = Path(config["runtime_env_file"])
    if not runtime_env.is_file():
        raise DeployError("production runtime environment file is missing")
    env_link = release / ".env"
    if env_link.exists() or env_link.is_symlink():
        if not env_link.is_symlink() or env_link.resolve() != runtime_env.resolve():
            raise DeployError("release .env already exists and is not the configured runtime symlink")
    else:
        env_link.symlink_to(runtime_env)

    # Both API and worker releases share the existing runtime image directory.
    # Never replace populated candidate directories or copy/delete user photos.
    shared_images = Path(config["legacy_dir"]) / "server" / "images"
    release_images = release / "server" / "images"
    if release_images.is_symlink():
        if release_images.resolve() != shared_images.resolve():
            raise DeployError("release images symlink points somewhere unexpected")
    else:
        if release_images.exists():
            if not release_images.is_dir() or any(release_images.iterdir()):
                raise DeployError("release images contains unexpected files; refusing replacement")
            release_images.rmdir()
        shared_images.mkdir(parents=True, exist_ok=True, mode=0o700)
        release_images.parent.mkdir(parents=True, exist_ok=True)
        release_images.symlink_to(shared_images, target_is_directory=True)

    legacy_models = Path(config["legacy_dir"]) / "server" / "models_onnx"
    release_models = release / "server" / "models_onnx"
    if legacy_models.exists():
        if release_models.is_symlink():
            if release_models.resolve() != legacy_models.resolve():
                raise DeployError("release models_onnx symlink points somewhere unexpected")
        else:
            if release_models.exists():
                if not release_models.is_dir():
                    raise DeployError("release models_onnx is not a directory")
                entries = list(release_models.iterdir())
                if any(not entry.is_file() or entry.suffix != ".onnx" for entry in entries):
                    raise DeployError("release models_onnx contains unexpected files; refusing replacement")
                for entry in entries:
                    entry.unlink()
                release_models.rmdir()
            release_models.symlink_to(legacy_models, target_is_directory=True)


def check_health(urls: tuple[str, ...] = ("http://127.0.0.1:8147/readyz", "http://127.0.0.1:8148/readyz"),
                 timeout: int = 60, opener: Callable[..., Any] = urlopen) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            healthy = True
            for url in urls:
                with opener(url, timeout=3) as response:
                    body = json.loads(response.read().decode("utf-8"))
                if not isinstance(body, dict) or body.get("ok") is not True or body.get("background_ready") is not True:
                    healthy = False
                    break
            if healthy:
                return True
        except (OSError, URLError, ValueError, json.JSONDecodeError):
            healthy = False
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(2, max(0, deadline - time.monotonic())))


def systemctl(action: str, service: str) -> None:
    run_checked(["sudo", "systemctl", action, f"gongxueyun-{service}.service"], timeout=90)


def restart_services() -> None:
    systemctl("start", "api")
    systemctl("start", "worker")


def stop_services() -> None:
    systemctl("stop", "worker")
    systemctl("stop", "api")


class Deployer:
    def __init__(self, config: dict[str, str], retry: bool = False):
        self.config = config
        self.retry = retry
        self.base = Path(config["base_dir"])
        self.legacy = Path(config["legacy_dir"])
        self.status_path = self.base / "status.json"
        self.current = self.base / "current"

    def deploy(self) -> str:
        self.base.mkdir(parents=True, exist_ok=True)
        with (self.base / "deploy.lock").open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            status = read_status(self.status_path)
            mirror = self.base / "source.git"
            sha = fetch_sha(self.config, mirror)
            if status["deployed"] == sha:
                LOG.info("commit %s is already deployed; skipping", sha)
                return "skipped"
            if status["attempt"] == sha and status["error"] and not self.retry:
                LOG.info("commit %s previously failed; skipping (use --retry)", sha)
                return "skipped"
            previous = str(self.current.resolve()) if self.current.is_symlink() else str(self.legacy)
            status.update(attempt=sha, previous=previous, error=None)
            atomic_json(self.status_path, status)
            release = self.base / "releases" / sha
            switched = False
            services_touched = False
            try:
                extract_release(mirror, sha, release)
                if migration_hash(Path(previous)) != migration_hash(release):
                    raise DeployError("MIGRATIONS changed; manual database migration is required")
                python = ensure_dependency_env(release, self.base, self.legacy)
                validate_release(release, python, self.config)
                install_runtime_links(release, self.config)
                prod_env = production_env(Path(self.config["runtime_env_file"]), self.legacy)
                create_database_backup(self.base, prod_env, self.legacy)
                services_touched = True
                stop_services()
                atomic_symlink(release, self.current)
                switched = True
                restart_services()
                if not check_health():
                    raise DeployError("new release failed readiness checks")
                status.update(deployed=sha, previous=previous, error=None)
                atomic_json(self.status_path, status)
                LOG.info("deployed commit %s", sha)
                return "deployed"
            except Exception as exc:
                rollback_health_failed = False
                if switched:
                    try:
                        stop_services()
                    except Exception:
                        LOG.exception("could not stop services before rollback")
                    atomic_symlink(Path(previous), self.current)
                if switched or services_touched:
                    try:
                        restart_services()
                    except Exception:
                        LOG.exception("could not restart services after rollback")
                    if switched and not check_health():
                        rollback_health_failed = True
                error = str(exc)[:500] if isinstance(exc, DeployError) else f"deployment failed ({type(exc).__name__})"
                if rollback_health_failed:
                    suffix = "; rollback release failed readiness checks"
                    error = f"{error[:500 - len(suffix)]}{suffix}"
                status["error"] = error
                atomic_json(self.status_path, status)
                raise


def load_config(path: Path) -> dict[str, str]:
    values = dict(DEFAULTS)
    if path.exists():
        try:
            custom = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeployError("deployment config is unreadable or invalid JSON") from exc
        if not isinstance(custom, dict):
            raise DeployError("deployment config must be a JSON object")
        unknown = set(custom) - set(DEFAULTS)
        if unknown:
            raise DeployError(f"unsupported config key(s): {', '.join(sorted(unknown))}")
        values.update({key: str(value) for key, value in custom.items()})
    safe_repo_url(values["repo_url"])
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/workspace/gxy-deploy/config.json")
    parser.add_argument("--retry", action="store_true", help="retry a commit whose previous attempt failed")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        result = Deployer(load_config(Path(args.config)), retry=args.retry).deploy()
        LOG.info("result: %s", result)
        return 0
    except BlockingIOError:
        LOG.error("another deployment is already running")
    except Exception as exc:
        LOG.error("deployment did not complete: %s", str(exc) if isinstance(exc, DeployError) else type(exc).__name__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
