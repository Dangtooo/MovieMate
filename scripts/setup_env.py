"""Prepare local configuration without replacing keys or deleting legacy data."""

from pathlib import Path
import re
import secrets

ROOT = Path(__file__).resolve().parents[1]


def setup():
    path = ROOT / ".env"
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    if not path.exists():
        path.write_text(
            example.replace(
                "replace_with_a_random_string_of_at_least_32_characters",
                secrets.token_hex(32),
            ),
            encoding="utf-8",
        )
        print("Created .env with SQLite and a random session secret.")
        return
    content = path.read_text(encoding="utf-8-sig")
    if re.search(r"^DATABASE_URL\s*=\s*[\"\']?postgres", content, flags=re.M):
        backup = ROOT / ".local" / ".env.before-sqlite"
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            backup.write_text(content, encoding="utf-8")
        content = re.sub(
            r"^DATABASE_URL\s*=.*$",
            "DATABASE_URL=sqlite:///./data/cinephile.db",
            content,
            flags=re.M,
        )
        print(
            "Switched .env to SQLite. Original config preserved in .local/.env.before-sqlite."
        )
    existing = {
        line.partition("=")[0].strip()
        for line in content.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    for line in example.splitlines():
        key, separator, value = line.partition("=")
        if separator and key not in existing:
            if key == "SECRET_KEY":
                value = secrets.token_hex(32)
            content = content.rstrip() + "\n" + key + "=" + value + "\n"
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    setup()
