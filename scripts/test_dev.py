"""Tests for the Typer dev orchestrator (scripts/dev.py).

Unit scope only: env layering, compose-ps parsing, child-env defaults,
service-set math, TCP probing. No docker, no child processes.
"""

from __future__ import annotations

import socket

import dev as devmod


def test_parse_env_file_skips_comments_and_strips_quotes(tmp_path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "# comment\n"
        "PLAIN=abc\n"
        'QUOTED="hello world"\n'
        "SINGLE='x y'\n"
        "EMPTY=\n"
        "NOEQUALS\n"
        "  SPACED = padded  \n"
    )
    env = devmod.parse_env_file(path)
    assert env == {
        "PLAIN": "abc",
        "QUOTED": "hello world",
        "SINGLE": "x y",
        "EMPTY": "",
        "SPACED": "padded",
    }


def test_parse_env_file_missing_returns_empty(tmp_path) -> None:
    assert devmod.parse_env_file(tmp_path / "nope.env") == {}


def test_merge_env_precedence_shell_over_env_over_defaults(monkeypatch, tmp_path) -> None:
    defaults = tmp_path / "one.env"
    secrets = tmp_path / "two.env"
    defaults.write_text("A=dev\nB=dev\nC=dev\n")
    secrets.write_text("B=secret\nC=secret\n")
    monkeypatch.setattr(devmod, "DEV_DEFAULTS", defaults)
    monkeypatch.setattr(devmod, "DEV_SECRETS", secrets)
    monkeypatch.setenv("C", "shell")
    merged = devmod.merge_env()
    assert (merged["A"], merged["B"], merged["C"]) == ("dev", "secret", "shell")


def test_build_child_env_sets_runtime_defaults_without_clobbering(monkeypatch) -> None:
    monkeypatch.delenv("PYTHONPATH", raising=False)
    env = devmod.build_child_env({"NODE_ENV": "production"})
    assert env["NODE_ENV"] == "production"
    assert env["PYTHONPATH"].split(":")[1] == "apps/ingest"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:5090/api/default"
    assert env["OTEL_EXPORTER_OTLP_HEADERS"].startswith("Authorization=Basic ")
    assert env["OTEL_SERVICE_NAME"] == "brb"


def test_otel_headers_derive_from_root_creds() -> None:
    import base64

    headers = devmod.otel_headers({"ZO_ROOT_USER_EMAIL": "a@b.c", "ZO_ROOT_USER_PASSWORD": "pw"})
    assert headers == "Authorization=Basic " + base64.b64encode(b"a@b.c:pw").decode()


def test_missing_services_reports_only_absent() -> None:
    assert devmod.missing_services(["a", "b", "c"], ["b"]) == ["a", "c"]
    assert devmod.missing_services(["a"], ["a"]) == []


def test_parse_compose_ps_docker_json_lines() -> None:
    payload = (
        '{"Service":"web","State":"running"}\n'
        '{"Service":"db","State":"exited"}\n'
        '{"Service":"cache","State":"running"}\n'
    )
    assert devmod.parse_compose_ps(payload) == ["web", "cache"]


def test_parse_compose_ps_podman_array_and_empty() -> None:
    payload = '[{"service":"web","state":"running"}, {"service":"db","state":"stopped"}]'
    assert devmod.parse_compose_ps(payload) == ["web"]
    assert devmod.parse_compose_ps("") == []
    assert devmod.parse_compose_ps("   \n") == []


def test_tcp_open_true_for_listening_socket() -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert devmod.tcp_open(port) is True
    finally:
        server.close()


def test_tcp_open_false_for_closed_port() -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.close()
    assert devmod.tcp_open(port, timeout=0.5) is False


def test_tag_styles_cover_expected_services() -> None:
    for tag in ("dev", "infra", "web", "ingest"):
        assert tag in devmod.TAG_STYLES


def test_expected_services_include_observability() -> None:
    assert "openobserve" in devmod.EXPECTED_SERVICES
    ports = {name: port for port, name in devmod.TCP_CHECKS}
    assert ports["openobserve"] == 5090


def test_style_for_known_worker_and_fallback() -> None:
    assert devmod.style_for("web", "web") == "bold cyan"
    assert devmod.style_for("radar-master", "ingest") == "bold yellow"
    first = devmod.WORKER_STYLES[0]
    assert devmod.style_for("radar-worker-1", "ingest") == first
    assert (
        devmod.style_for("radar-worker-7", "ingest")
        == devmod.WORKER_STYLES[6 % len(devmod.WORKER_STYLES)]
    )
    assert devmod.style_for("mystery", "ingest") == "bold magenta"
    assert devmod.style_for("mystery", "nope") == "white"


def test_split_child_prefix() -> None:
    assert devmod.split_child_prefix("[radar-worker-2] hello") == ("radar-worker-2", "hello")
    assert devmod.split_child_prefix("plain line") == (None, "plain line")
    assert devmod.split_child_prefix("[radar-master]") == ("radar-master", "")


def test_format_line_retags_grandchild_and_ignores_markup() -> None:
    text = devmod.format_line("ingest", "[radar-worker-1] [not-a-style] hi")
    rendered = text.plain
    assert rendered == "[radar-worker-1] [not-a-style] hi"
    assert text.spans[0].style == devmod.style_for("radar-worker-1", "ingest")
