import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _render_compose(**environment_overrides: str) -> dict:
    environment = os.environ.copy()
    environment.update(
        {
            "B2T_CONFIG_PATH": "./config.toml",
            "B2T_SUMMARY_PRESETS_PATH": "./summary_presets.toml",
            "B2T_CONTEXT_PATH": "./context.toml",
            "B2T_TRANSCRIPTIONS_DIR": "./transcriptions",
            "B2T_DB_DIR": "./db_data",
            "B2T_CHROMA_DIR": "./chroma_data",
            **environment_overrides,
        }
    )
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_rag_streaming_proxy_allows_long_idle_intervals() -> None:
    template = Path("docker/nginx.compose.conf.template").read_text(encoding="utf-8")

    assert "proxy_read_timeout 600s;" in template
    assert "proxy_buffering off;" in template


def test_compose_uses_the_configured_timezone_for_both_services() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "TZ: ${B2T_TIMEZONE:-Asia/Shanghai}" in compose
    assert compose.count("TZ: ${B2T_TIMEZONE:-Asia/Shanghai}") == 2
    assert "B2T_TIMEZONE=Asia/Shanghai" in env_example


def test_runtime_images_install_timezone_data() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "ffmpeg pandoc tzdata" in dockerfile
    assert "RUN apk add --no-cache tzdata" in dockerfile


def test_compose_keeps_host_outputs_but_manages_yutto_config() -> None:
    compose = _render_compose()
    compose_source = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    backend_mounts = {
        mount["target"]: mount for mount in compose["services"]["backend"]["volumes"]
    }

    expected_bind_mounts = {
        "/app/config.toml": PROJECT_ROOT / "config.toml",
        "/app/summary_presets.toml": PROJECT_ROOT / "summary_presets.toml",
        "/app/context.toml": PROJECT_ROOT / "context.toml",
        "/app/transcriptions": PROJECT_ROOT / "transcriptions",
        "/app/db_data": PROJECT_ROOT / "db_data",
        "/app/chroma_data": PROJECT_ROOT / "chroma_data",
    }
    for target, source in expected_bind_mounts.items():
        mount = backend_mounts[target]
        assert mount["type"] == "bind"
        assert Path(mount["source"]) == source
        assert mount["bind"].get("create_host_path") is not True

    assert compose_source.count("create_host_path: false") == len(expected_bind_mounts)
    for target in (
        "/app/config.toml",
        "/app/summary_presets.toml",
        "/app/context.toml",
    ):
        assert backend_mounts[target]["read_only"] is True

    yutto_mount = backend_mounts["/home/appuser/.config"]
    assert yutto_mount["type"] == "volume"
    assert yutto_mount["source"] == "yutto_config"
    assert "/home/appuser/.config/yutto/auth.toml" not in backend_mounts


def test_compose_uses_the_same_configurable_uid_and_gid_at_build_and_runtime() -> None:
    compose = _render_compose(B2T_UID="23456", B2T_GID="23457")
    backend = compose["services"]["backend"]
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert backend["build"]["args"] == {
        "APP_GID": "23457",
        "APP_UID": "23456",
    }
    assert backend["user"] == "23456:23457"
    assert 'getent group "${APP_GID}"' in dockerfile
    assert 'getent passwd "${APP_UID}"' in dockerfile
    assert "ENV HOME=/home/appuser" in dockerfile
    assert "USER ${APP_UID}:${APP_GID}" in dockerfile
