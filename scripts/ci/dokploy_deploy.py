"""Deploy published BRB images through Dokploy's authenticated HTTPS API."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from urllib.parse import urlencode, urlsplit


class Dokploy:
    def __init__(self) -> None:
        self.base = os.environ["DOKPLOY_API_URL"].rstrip("/").removesuffix("/api")
        parsed = urlsplit(self.base)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("DOKPLOY_API_URL must be an HTTPS URL")
        self.token = os.environ["DOKPLOY_API_TOKEN"]
        if not self.token:
            raise ValueError("DOKPLOY_API_TOKEN is empty")

    def request(self, route: str, payload: dict | None = None, **query):
        url = f"{self.base}/api/{route}"
        if query:
            url += "?" + urlencode(query)
        # No redirects: never forward the API key to a different host.
        args = [
            "curl",
            "--proto",
            "=https",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "10",
            "--max-time",
            "60",
            "--header",
            f"x-api-key: {self.token}",
            "--header",
            "Accept: application/json",
            "--write-out",
            "\n%{http_code}",
            url,
        ]
        if payload is not None:
            args += ["--request", "POST", "--header", "Content-Type: application/json"]
            args += ["--data-binary", "@-"]
        result = subprocess.run(
            args,
            input=json.dumps(payload) if payload is not None else None,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"Dokploy {route}: transport failure ({result.returncode})")
        body, _, status = result.stdout.rpartition("\n")
        if not status.startswith("2"):
            # API responses can contain saved environment secrets; never print them.
            raise RuntimeError(f"Dokploy {route}: HTTP {status}")
        return json.loads(body) if body.strip() else None


def assert_project(service: dict, expected: str) -> None:
    environment = service.get("environment", {})
    if environment.get("projectId") != expected:
        raise ValueError("Dokploy target does not belong to the configured BRB project")


def wait_for_deployment(client: Dokploy, route: str, query: dict, previous: set[str]) -> None:
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        deployments = client.request(route, **query)
        new = [d for d in deployments if d["deploymentId"] not in previous]
        if new:
            # Dokploy returns the newest first. A failed deployment must fail CI.
            status = new[0]["status"]
            if status == "done":
                print("Dokploy deployment completed.")
                return
            if status in ("error", "cancelled", "canceled"):
                raise RuntimeError(f"Dokploy deployment {status}")
        time.sleep(10)
    raise TimeoutError("Dokploy deployment did not finish within 15 minutes")


def wait_for_healthy_image(client: Dokploy, app_name: str, image: str) -> None:
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        containers = client.request("docker.getContainers")
        running = [
            container
            for container in containers
            if container.get("name", "").startswith(f"{app_name}.")
            and container.get("state") == "running"
            and container.get("image") == image
        ]
        if running and all("(healthy)" in c.get("status", "") for c in running):
            print(f"Verified healthy containers for {app_name}.")
            return
        time.sleep(10)
    raise TimeoutError(f"No healthy container for the expected {app_name} image")


def wait_for_migration(
    client: Dokploy, app_name: str, image: str, previous_containers: set[str]
) -> None:
    # Dokploy's deployment status means Swarm accepted the service. A one-shot
    # migration is successful only after its NEW container actually exits zero.
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        containers = client.request("docker.getContainers")
        fresh = [
            c
            for c in containers
            if c.get("name", "").startswith(f"{app_name}.")
            and c.get("image") == image
            and c.get("containerId") not in previous_containers
        ]
        for container in fresh:
            config = client.request("docker.getConfig", containerId=container["containerId"])
            if isinstance(config, str):
                config = json.loads(config)
            if isinstance(config, list):
                config = config[0]
            state = config["State"]
            if state.get("Running") or state.get("Status") == "created":
                continue
            if state.get("Status") in ("exited", "dead"):
                if state.get("ExitCode") != 0 or state.get("OOMKilled"):
                    raise RuntimeError("Prisma migration container failed; app rollout blocked")
                print("Prisma migrations applied and schema verified (container exited 0).")
                return
        time.sleep(10)
    raise TimeoutError("Prisma migration container did not complete within 15 minutes")


def verify_web(url: str, sha: str) -> None:
    for _ in range(36):
        response = subprocess.run(
            ["curl", "--proto", "=https", "-fsS", "--max-time", "15", f"{url}/?release={sha}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if response.returncode == 0 and f'content="{sha}"' in response.stdout:
            print(f"Verified public web revision {sha}.")
            return
        time.sleep(10)
    raise RuntimeError("The public landing page did not serve the expected revision")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--migrations", action="store_true")
    args = parser.parse_args()
    client = Dokploy()
    project_id = os.environ["DOKPLOY_PROJECT_ID"]
    app_id = os.environ["DOKPLOY_WEB_APP_ID"]
    ingest_id = os.environ["DOKPLOY_INGEST_APP_ID"]
    web = client.request("application.one", applicationId=app_id)
    ingest = client.request("application.one", applicationId=ingest_id)
    assert_project(web, project_id)
    assert_project(ingest, project_id)
    prisma_id = os.environ["DOKPLOY_PRISMA_APP_ID"]
    prisma = client.request("application.one", applicationId=prisma_id)
    assert_project(prisma, project_id)
    if args.check:
        print("Dokploy credentials and all three BRB deployment targets verified.")
        return
    sha = os.environ["GITHUB_SHA"]
    owner = os.environ["GITHUB_REPOSITORY_OWNER"].lower()
    title = f"GitHub main {sha[:12]}"
    if args.web or args.ingest or args.migrations:
        # No dependent rollout can bypass schema readiness, including retries
        # of an apps-only deployment after a failed migration.
        image = f"ghcr.io/{owner}/brb-prisma-sync:sha-{sha}"
        previous_containers = {
            c["containerId"]
            for c in client.request("docker.getContainers")
            if c.get("name", "").startswith(f"{prisma['appName']}.")
        }
        previous_deployments = {
            d["deploymentId"] for d in client.request("deployment.all", applicationId=prisma_id)
        }
        client.request("application.update", {"applicationId": prisma_id, "dockerImage": image})
        client.request("application.deploy", {"applicationId": prisma_id, "title": title})
        wait_for_deployment(
            client, "deployment.all", {"applicationId": prisma_id}, previous_deployments
        )
        wait_for_migration(client, prisma["appName"], image, previous_containers)
    if args.web:
        previous = {
            d["deploymentId"] for d in client.request("deployment.all", applicationId=app_id)
        }
        client.request(
            "application.update",
            {
                "applicationId": app_id,
                "dockerImage": f"ghcr.io/{owner}/brb-web:sha-{sha}",
            },
        )
        client.request("application.deploy", {"applicationId": app_id, "title": title})
        wait_for_deployment(client, "deployment.all", {"applicationId": app_id}, previous)
        wait_for_healthy_image(client, web["appName"], f"ghcr.io/{owner}/brb-web:sha-{sha}")
        verify_web(os.environ["BRB_WEB_URL"], sha)
    if args.ingest:
        previous = {
            d["deploymentId"] for d in client.request("deployment.all", applicationId=ingest_id)
        }
        client.request(
            "application.update",
            {
                "applicationId": ingest_id,
                "dockerImage": f"ghcr.io/{owner}/brb-ingest:sha-{sha}",
            },
        )
        client.request("application.deploy", {"applicationId": ingest_id, "title": title})
        wait_for_deployment(client, "deployment.all", {"applicationId": ingest_id}, previous)
        wait_for_healthy_image(client, ingest["appName"], f"ghcr.io/{owner}/brb-ingest:sha-{sha}")


if __name__ == "__main__":
    main()
