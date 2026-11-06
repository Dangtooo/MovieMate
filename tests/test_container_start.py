"""Deployment startup must configure origins before loading application settings."""

import os

import pytest

from scripts import container_start


def test_render_origin_is_added_without_losing_custom_domains(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://moviemate-123.onrender.com/")
    monkeypatch.setenv("ALLOWED_ORIGINS", " https://movies.example.com/ ,https://movies.example.com")
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.setenv("PORT", "12345")
    assert container_start.configure_environment() == 12345
    assert os.environ["ALLOWED_ORIGINS"] == (
        "https://movies.example.com,https://moviemate-123.onrender.com"
    )
    assert os.environ["COOKIE_SECURE"] == "true"


def test_local_start_preserves_http_cookie_setting(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:8000")
    monkeypatch.delenv("PORT", raising=False)
    assert container_start.configure_environment() == 10000
    assert os.environ["COOKIE_SECURE"] == "false"
    assert os.environ["ALLOWED_ORIGINS"] == "http://localhost:8000"


@pytest.mark.parametrize("secret", ["", "short", "replace_with_a_random_string_of_at_least_32_characters"])
def test_deployment_requires_private_signing_secret(monkeypatch, secret):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("SECRET_KEY", secret)
    with pytest.raises(ValueError, match="SECRET_KEY"):
        container_start.configure_environment()


@pytest.mark.parametrize("url", ["", "http://app.onrender.com", "https://app.onrender.com/path"])
def test_invalid_render_origin_is_not_added(monkeypatch, url):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", url)
    with pytest.raises(ValueError, match="RENDER_EXTERNAL_URL"):
        container_start.configure_environment()


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_invalid_listening_port(monkeypatch, port):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("PORT", port)
    with pytest.raises(ValueError):
        container_start.configure_environment()


@pytest.mark.parametrize("seed_enabled", [True, False])
def test_main_seeds_optionally_and_executes_exactly_one_worker(monkeypatch, seed_enabled):
    from backend import demo_catalog

    events = []
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("PORT", "12345")
    monkeypatch.setenv("SEED_DEMO_DATA", str(seed_enabled).lower())
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
    monkeypatch.setattr(container_start, "prepare_disk_and_drop_privileges", lambda: events.append("privileges dropped"))
    monkeypatch.setattr(demo_catalog, "seed", lambda: events.append("seed"))
    executed = []
    monkeypatch.setattr(os, "execv", lambda executable, argv: executed.append(argv))
    container_start.main()
    assert events == ["privileges dropped"] + (["seed"] if seed_enabled else [])
    command = executed[0]
    assert command[1:4] == ["-m", "uvicorn", "backend.main:app"]
    assert command[command.index("--host") + 1] == "0.0.0.0"
    assert command[command.index("--port") + 1] == "12345"
    assert command[command.index("--workers") + 1] == "1"
    assert "--reload" not in command
