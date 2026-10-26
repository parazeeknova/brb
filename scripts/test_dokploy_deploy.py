"""Deployment safeguards: HTTPS, project ownership and failure handling."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "dokploy_deploy", Path(__file__).parent / "ci" / "dokploy_deploy.py"
)
assert SPEC is not None and SPEC.loader is not None
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


def test_another_project_is_rejected() -> None:
    with pytest.raises(ValueError, match="BRB project"):
        deploy.assert_project({"environment": {"projectId": "other"}}, "brb")


def test_deploy_requires_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOKPLOY_API_URL", "http://example.com")
    with pytest.raises(ValueError, match="HTTPS"):
        deploy.Dokploy()


def test_failed_deployment_fails_ci() -> None:
    class Client:
        def request(self, *_args, **_kwargs):
            return [{"deploymentId": "new", "status": "error"}]

    with pytest.raises(RuntimeError, match="error"):
        deploy.wait_for_deployment(Client(), "deployment.all", {}, {"old"})


@pytest.mark.parametrize("exit_code,oom", [(1, False), (0, True)])
def test_failed_migration_container_blocks_rollout(exit_code: int, oom: bool) -> None:
    class Client:
        def request(self, route, **_kwargs):
            if route == "docker.getContainers":
                return [{"containerId": "new", "name": "migrations.1.new", "image": "sha-new"}]
            return {"State": {"Status": "exited", "ExitCode": exit_code, "OOMKilled": oom}}

    with pytest.raises(RuntimeError, match="rollout blocked"):
        deploy.wait_for_migration(Client(), "migrations", "sha-new", {"old"})


def test_migration_waits_for_new_container_not_previous_success(monkeypatch) -> None:
    calls = []

    class Client:
        def request(self, route, **_kwargs):
            calls.append(route)
            if route == "docker.getContainers":
                return [{"containerId": "old", "name": "migrations.1.old", "image": "sha-new"}]
            pytest.fail("Previous successful container must never satisfy the gate")

    ticks = iter([0, 0, 1000])
    monkeypatch.setattr(deploy.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(deploy.time, "sleep", lambda _: None)
    with pytest.raises(TimeoutError, match="did not complete"):
        deploy.wait_for_migration(Client(), "migrations", "sha-new", {"old"})
    assert calls == ["docker.getContainers"]
