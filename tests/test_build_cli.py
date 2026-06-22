from __future__ import annotations

import subprocess
import tempfile
import unittest
import contextlib
import io
from pathlib import Path
from unittest import mock

from atsuite.cli import build_docker_images as build_cli


class BuildDockerImagesTests(unittest.TestCase):
    def test_aws_agentcore_falls_back_to_docker_build_when_buildx_missing(self) -> None:
        captured = []

        def fake_subprocess_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, args[0])

        def fake_run(cmd, **kwargs):
            captured.append(cmd)

        with tempfile.TemporaryDirectory() as tmp:
            context = Path(tmp)
            dockerfile = context / "Dockerfile"
            dockerfile.write_text("FROM scratch\n", encoding="utf-8")
            with mock.patch.object(build_cli.subprocess, "run", side_effect=fake_subprocess_run):
                with mock.patch.object(build_cli, "run", side_effect=fake_run):
                    with contextlib.redirect_stderr(io.StringIO()):
                        build_cli.build_node_image(
                            "example:latest",
                            context,
                            dockerfile,
                            python_version="3.11",
                            provider="aws_agentcore",
                            base_image="python:3.11-slim",
                            platform="linux/arm64",
                        )

        self.assertEqual(captured[0][:3], ["docker", "build", "-f"])
        self.assertIn("--platform", captured[0])
        self.assertIn("linux/arm64", captured[0])
        self.assertNotIn("buildx", captured[0])

    def test_system_packages_are_opt_in_build_args(self) -> None:
        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(cmd)

        with tempfile.TemporaryDirectory() as tmp:
            context = Path(tmp)
            dockerfile = context / "Dockerfile"
            dockerfile.write_text("FROM scratch\n", encoding="utf-8")
            with mock.patch.object(build_cli, "run", side_effect=fake_run):
                build_cli.build_node_image(
                    "example:default",
                    context,
                    dockerfile,
                    python_version="3.11",
                    provider="aws_lambda",
                    base_image="python:3.11-slim",
                )
                build_cli.build_node_image(
                    "example:git",
                    context,
                    dockerfile,
                    python_version="3.11",
                    provider="aws_lambda",
                    base_image="python:3.11-slim",
                    system_packages=["git", "ca-certificates"],
                )

        default_cmd = captured[0]
        git_cmd = captured[1]
        self.assertFalse(any("ATSUITE_SYSTEM_PACKAGES" in part for part in default_cmd))
        self.assertIn(
            "ATSUITE_SYSTEM_PACKAGES=ca-certificates git",
            git_cmd,
        )


if __name__ == "__main__":
    unittest.main()
