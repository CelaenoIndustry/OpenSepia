#!/usr/bin/env python3
"""
AI Dev Team — Docker Integration
DevOps agent manages Docker containers inside the LXC container.
Supports docker and docker-compose.
"""

import os
import subprocess
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class DockerConfig:
    def __init__(self) -> None:
        # Docker socket (default or custom)
        self.docker_host: str = os.getenv("DOCKER_HOST", "")
        # Registry for push/pull
        self.registry: str = os.getenv("DOCKER_REGISTRY", "")
        self.registry_user: str = os.getenv("DOCKER_REGISTRY_USER", "")
        self.registry_pass: str = os.getenv("DOCKER_REGISTRY_PASS", "")
        # Prefix for image names
        self.image_prefix: str = os.getenv("DOCKER_IMAGE_PREFIX", "")
        # Compose file
        self.compose_file: str = os.getenv("DOCKER_COMPOSE_FILE", "docker-compose.yml")
        # Security limits
        try:
            self.max_containers: int = int(os.getenv("DOCKER_MAX_CONTAINERS", "10"))
        except ValueError:
            logger.warning("DOCKER_MAX_CONTAINERS is not a valid integer — defaulting to 10")
            self.max_containers = 10
        if self.max_containers < 1:
            logger.warning("DOCKER_MAX_CONTAINERS must be positive — defaulting to 10")
            self.max_containers = 10
        self.allowed_networks: list[str] = os.getenv("DOCKER_ALLOWED_NETWORKS", "bridge,host").split(",")

    @property
    def is_configured(self) -> bool:
        # Docker is "configured" if running on the host
        return True  # Always available inside LXC


class DockerClient:
    """Docker operations for the DevOps agent."""

    def __init__(self, config: Optional[DockerConfig] = None) -> None:
        self.config = config or DockerConfig()

    def _parse_json_lines(self, output: str) -> list[dict]:
        """Parse newline-delimited JSON output from docker commands."""
        items: list[dict] = []
        for line in output.strip().split("\n"):
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.debug("Failed to parse JSON line: %s", line[:200])
        return items

    def _run(self, *args: str, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
        """Run a docker command."""
        cmd = ["docker"] + list(args)

        env = os.environ.copy()
        if self.config.docker_host:
            env["DOCKER_HOST"] = self.config.docker_host

        logger.debug(f"docker {' '.join(args)}")

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env
        )

        if check and result.returncode != 0:
            logger.error(f"docker {args[0]} failed: {result.stderr}")

        return result

    def _run_compose(self, *args: str, cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
        """Run a docker-compose command."""
        cmd = ["docker", "compose"] + list(args)

        env = os.environ.copy()
        if self.config.docker_host:
            env["DOCKER_HOST"] = self.config.docker_host

        logger.debug(f"docker compose {' '.join(args)}")

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            cwd=str(cwd) if cwd else None, env=env
        )

        if check and result.returncode != 0:
            logger.error(f"docker compose {args[0]} failed: {result.stderr}")

        return result

    # =========================================================================
    # State information
    # =========================================================================

    def ps(self, all: bool = False) -> list[dict]:
        """List running containers."""
        args = ["ps", "--format", "json"]
        if all:
            args.append("-a")

        result = self._run(*args, check=False)
        if result.returncode != 0:
            return []

        return self._parse_json_lines(result.stdout)

    def inspect(self, container: str) -> dict:
        """Detailed info about a container."""
        result = self._run("inspect", container, check=False)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data[0] if data else {}
        return {"error": result.stderr}

    def logs(self, container: str, tail: int = 100, since: Optional[str] = None) -> str:
        """Logs from a container."""
        args = ["logs", f"--tail={tail}"]
        if since:
            args.append(f"--since={since}")
        args.append(container)

        result = self._run(*args, check=False)
        # Docker logs go to stderr
        return result.stdout + result.stderr

    def stats(self, container: Optional[str] = None) -> str:
        """Resource usage statistics."""
        args = ["stats", "--no-stream", "--format",
                "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"]
        if container:
            args.append(container)

        result = self._run(*args, check=False)
        return result.stdout

    def images(self) -> list[dict]:
        """List local images."""
        result = self._run("images", "--format", "json", check=False)
        if result.returncode != 0:
            return []

        return self._parse_json_lines(result.stdout)

    # =========================================================================
    # Build
    # =========================================================================

    def build(self, path: str = ".", tag: Optional[str] = None, dockerfile: Optional[str] = None,
              build_args: Optional[dict] = None, no_cache: bool = False) -> dict:
        """Build Docker image."""
        args = ["build"]

        if tag:
            full_tag = f"{self.config.image_prefix}{tag}" if self.config.image_prefix else tag
            args.extend(["-t", full_tag])

        if dockerfile:
            args.extend(["-f", dockerfile])

        if no_cache:
            args.append("--no-cache")

        if build_args:
            for k, v in build_args.items():
                args.extend(["--build-arg", f"{k}={v}"])

        args.append(path)

        result = self._run(*args, check=False, timeout=600)

        return {
            "success": result.returncode == 0,
            "tag": tag,
            "output": result.stdout[-2000:] if result.stdout else "",  # Last 2000 characters
            "error": result.stderr if result.returncode != 0 else "",
        }

    # =========================================================================
    # Run / Start / Stop
    # =========================================================================

    def run(self, image: str, name: Optional[str] = None, ports: Optional[dict] = None,
            volumes: Optional[dict] = None, env: Optional[dict] = None, network: Optional[str] = None,
            detach: bool = True, restart: str = "unless-stopped",
            command: Optional[str] = None, labels: Optional[dict] = None) -> dict:
        """Run a new container."""

        # Security check for container count
        running = self.ps()
        if len(running) >= self.config.max_containers:
            return {"error": f"Container limit ({self.config.max_containers}) reached"}

        # Network check
        if network and network not in self.config.allowed_networks:
            return {"error": f"Network '{network}' is not allowed"}

        args = ["run"]

        if detach:
            args.append("-d")

        if name:
            args.extend(["--name", name])

        if restart:
            args.extend(["--restart", restart])

        if network:
            args.extend(["--network", network])

        if ports:
            for host_port, container_port in ports.items():
                args.extend(["-p", f"{host_port}:{container_port}"])

        if volumes:
            for host_path, container_path in volumes.items():
                args.extend(["-v", f"{host_path}:{container_path}"])

        if env:
            for k, v in env.items():
                args.extend(["-e", f"{k}={v}"])

        if labels:
            for k, v in labels.items():
                args.extend(["--label", f"{k}={v}"])

        # Add label to identify AI-managed containers
        args.extend(["--label", "managed-by=ai-team"])
        args.extend(["--label", f"created-at={datetime.now().isoformat()}"])

        args.append(image)

        if command:
            args.extend(command.split())

        result = self._run(*args, check=False)

        if result.returncode == 0:
            container_id = result.stdout.strip()[:12]
            logger.info(f"Container {name or container_id} started")
            return {
                "success": True,
                "container_id": container_id,
                "name": name,
            }
        else:
            return {
                "success": False,
                "error": result.stderr,
            }

    def start(self, container: str) -> dict:
        """Start a stopped container."""
        result = self._run("start", container, check=False)
        return {
            "success": result.returncode == 0,
            "error": result.stderr if result.returncode != 0 else "",
        }

    def stop(self, container: str, timeout: int = 10) -> dict:
        """Stop a container."""
        result = self._run("stop", "-t", str(timeout), container, check=False)
        return {
            "success": result.returncode == 0,
            "error": result.stderr if result.returncode != 0 else "",
        }

    def restart(self, container: str) -> dict:
        """Restart a container."""
        result = self._run("restart", container, check=False)
        return {
            "success": result.returncode == 0,
            "error": result.stderr if result.returncode != 0 else "",
        }

    def rm(self, container: str, force: bool = False) -> dict:
        """Remove a container."""
        args = ["rm"]
        if force:
            args.append("-f")
        args.append(container)

        result = self._run(*args, check=False)
        return {
            "success": result.returncode == 0,
            "error": result.stderr if result.returncode != 0 else "",
        }

    def pull(self, image: str) -> dict:
        """Pull an image from registry."""
        result = self._run("pull", image, check=False, timeout=300)
        return {
            "success": result.returncode == 0,
            "error": result.stderr if result.returncode != 0 else "",
        }

    def push(self, image: str) -> dict:
        """Push an image to registry."""
        # Login if configured
        if self.config.registry_user and self.config.registry_pass:
            login_cmd = ["docker", "login", self.config.registry,
                         "-u", self.config.registry_user, "--password-stdin"]
            env = os.environ.copy()
            if self.config.docker_host:
                env["DOCKER_HOST"] = self.config.docker_host
            login = subprocess.run(
                login_cmd, input=self.config.registry_pass,
                capture_output=True, text=True, timeout=30, env=env
            )
            if login.returncode != 0:
                return {"success": False, "error": f"Login failed: {login.stderr}"}

        result = self._run("push", image, check=False, timeout=300)
        return {
            "success": result.returncode == 0,
            "error": result.stderr if result.returncode != 0 else "",
        }

    # =========================================================================
    # Docker Compose
    # =========================================================================

    def compose_up(self, cwd: Optional[Path] = None, services: Optional[list[str]] = None,
                   detach: bool = True, build: bool = False) -> dict:
        """Start a docker-compose stack."""
        args = ["up"]

        if detach:
            args.append("-d")
        if build:
            args.append("--build")
        if services:
            args.extend(services)

        result = self._run_compose(*args, cwd=cwd, check=False)
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else "",
        }

    def compose_down(self, cwd: Optional[Path] = None, volumes: bool = False) -> dict:
        """Stop a docker-compose stack."""
        args = ["down"]
        if volumes:
            args.append("-v")

        result = self._run_compose(*args, cwd=cwd, check=False)
        return {
            "success": result.returncode == 0,
            "error": result.stderr if result.returncode != 0 else "",
        }

    def compose_ps(self, cwd: Optional[Path] = None) -> str:
        """Docker-compose stack state."""
        result = self._run_compose("ps", cwd=cwd, check=False)
        return result.stdout

    def compose_logs(self, cwd: Optional[Path] = None, services: Optional[list[str]] = None,
                     tail: int = 100) -> str:
        """Logs from a docker-compose stack."""
        args = ["logs", f"--tail={tail}"]
        if services:
            args.extend(services)

        result = self._run_compose(*args, cwd=cwd, check=False)
        return result.stdout + result.stderr

    def compose_restart(self, cwd: Optional[Path] = None, services: Optional[list[str]] = None) -> dict:
        """Restart docker-compose services."""
        args = ["restart"]
        if services:
            args.extend(services)

        result = self._run_compose(*args, cwd=cwd, check=False)
        return {
            "success": result.returncode == 0,
            "error": result.stderr if result.returncode != 0 else "",
        }

    # =========================================================================
    # Deploy helper (build + run)
    # =========================================================================

    def deploy(self, image: str, name: str, tag: str = "latest",
               build_path: Optional[str] = None, ports: Optional[dict] = None,
               volumes: Optional[dict] = None, env: Optional[dict] = None) -> dict:
        """
        Full deploy: build (optional) -> stop old -> run new.
        Main method for the DevOps agent.
        """
        result = {
            "built": False,
            "stopped_old": False,
            "started_new": False,
            "container_id": None,
            "errors": [],
        }

        full_image = f"{image}:{tag}"

        # 1. Build if a path is provided
        if build_path:
            build_result = self.build(path=build_path, tag=full_image)
            if not build_result.get("success"):
                result["errors"].append(f"Build failed: {build_result.get('error')}")
                return result
            result["built"] = True

        # 2. Stop and remove old container with the same name
        existing = self._run("ps", "-aq", "-f", f"name={name}", check=False)
        if existing.stdout.strip():
            self.stop(name)
            self.rm(name, force=True)
            result["stopped_old"] = True

        # 3. Run new container
        run_result = self.run(
            image=full_image,
            name=name,
            ports=ports,
            volumes=volumes,
            env=env,
        )

        if run_result.get("success"):
            result["started_new"] = True
            result["container_id"] = run_result.get("container_id")
        else:
            result["errors"].append(f"Run failed: {run_result.get('error')}")

        return result

    # =========================================================================
    # Context for agent
    # =========================================================================

    def get_docker_context_md(self) -> str:
        """Return Docker state as Markdown for agents."""
        lines = ["## 🐳 Docker Status\n"]

        # Running containers
        containers = self.ps(all=True)
        running = [c for c in containers if c.get("State") == "running"]
        stopped = [c for c in containers if c.get("State") != "running"]

        lines.append(f"### Running containers ({len(running)})")
        if running:
            for c in running:
                name = c.get("Names", "?")
                image = c.get("Image", "?")
                status = c.get("Status", "?")
                ports = c.get("Ports", "")
                lines.append(f"- **{name}** — `{image}`")
                lines.append(f"  - Status: {status}")
                if ports:
                    lines.append(f"  - Ports: {ports}")
        else:
            lines.append("_(none)_")

        lines.append("")

        if stopped:
            lines.append(f"### Stopped containers ({len(stopped)})")
            for c in stopped[:5]:  # Max 5
                name = c.get("Names", "?")
                status = c.get("Status", "?")
                lines.append(f"- {name}: {status}")
            lines.append("")

        # Resource usage
        lines.append("### Resource usage")
        stats = self.stats()
        if stats.strip():
            lines.append(f"```\n{stats}\n```")
        else:
            lines.append("_(unavailable)_")

        # Local images
        images = self.images()
        if images:
            lines.append(f"\n### Local images ({len(images)})")
            for img in images[:10]:  # Max 10
                repo = img.get("Repository", "?")
                tag = img.get("Tag", "?")
                size = img.get("Size", "?")
                lines.append(f"- `{repo}:{tag}` ({size})")

        return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================
if __name__ == "__main__":
    import sys

    client = DockerClient()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        print(client.get_docker_context_md())
    elif cmd == "ps":
        for c in client.ps():
            print(f"{c.get('Names')}: {c.get('Status')}")
    elif cmd == "logs":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        if name:
            print(client.logs(name))
        else:
            print("Usage: docker_client.py logs <container>")
    elif cmd == "deploy":
        # Example: docker_client.py deploy myapp:latest myapp-container
        image = sys.argv[2] if len(sys.argv) > 2 else "nginx:latest"
        name = sys.argv[3] if len(sys.argv) > 3 else "test-container"
        result = client.deploy(image, name, ports={"8080": "80"})
        print(json.dumps(result, indent=2))
    else:
        print("Usage: docker_client.py [status|ps|logs|deploy]")
