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
