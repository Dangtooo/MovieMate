"""Initialize the mounted SQLite directory and launch one application worker."""

import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


def configure_environment():
    """Set runtime defaults before importing backend.config or creating engines."""
    if os.environ.get("RENDER") == "true":
        os.environ.setdefault("COOKIE_SECURE", "true")
        external_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
        parsed = urlsplit(external_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path:
            raise ValueError("Render must provide a valid HTTPS RENDER_EXTERNAL_URL.")
        # Preserve explicitly configured custom domains and add Render's real URL.
        origins = [
            origin.strip().rstrip("/")
            for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        ]
        os.environ["ALLOWED_ORIGINS"] = ",".join(dict.fromkeys([*origins, external_url]))

    secret = os.environ.get("SECRET_KEY", "")
    if len(secret) < 32 or secret.startswith("replace_with_"):
        raise ValueError("Set a private SECRET_KEY of at least 32 characters.")
    port = int(os.environ.get("PORT", "10000"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535.")
    return port


def prepare_disk_and_drop_privileges():
    """Render mounts new disks at runtime; the mount can initially be root-owned."""
    if os.name != "posix" or os.geteuid() != 0:
        return
    import pwd

    account = pwd.getpwnam("moviemate")
    # Limit permission changes to this application's known data directories/files.
    for folder in (Path("/var/data/moviemate"), Path("/app/data")):
        folder.mkdir(parents=True, exist_ok=True)
        os.chown(folder, account.pw_uid, account.pw_gid)
        for filename in ("moviemate.db", "moviemate.db-wal", "moviemate.db-shm"):
            db_file = folder / filename
            if db_file.is_file() and not db_file.is_symlink():
                os.chown(db_file, account.pw_uid, account.pw_gid)
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    os.environ["HOME"] = account.pw_dir


def main():
    port = configure_environment()
    prepare_disk_and_drop_privileges()
    seed = os.environ.get("SEED_DEMO_DATA", "true").strip().lower()
    if seed not in {"true", "false"}:
        raise ValueError("SEED_DEMO_DATA must be true or false.")
    if seed == "true":
        from backend.demo_catalog import seed as seed_catalog

        # ON CONFLICT DO NOTHING preserves existing movies, reviews and accounts.
        seed_catalog()

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--workers",
        "1",
        "--proxy-headers",
        "--forwarded-allow-ips",
        os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    ]
    os.execv(sys.executable, command)


if __name__ == "__main__":
    main()
