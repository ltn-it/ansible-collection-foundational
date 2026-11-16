"""Contract tests for the native Podman kube Quadlet controller."""

from pathlib import Path
import unittest

import yaml
from jinja2 import Environment, StrictUndefined


ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT / "roles" / "podman_systemd"


class PodmanSystemdContractTests(unittest.TestCase):
    def test_networks_default_to_no_override(self) -> None:
        defaults = yaml.safe_load(
            (ROLE / "defaults" / "main.yml").read_text(encoding="utf-8")
        )

        self.assertEqual(defaults["podman_systemd_networks"], [])

    def test_network_options_are_native_quadlet_entries(self) -> None:
        template = (ROLE / "templates" / "kube.quadlet.j2").read_text(
            encoding="utf-8"
        )

        self.assertIn("{% for network in podman_systemd_networks %}", template)
        self.assertIn("Network={{ network }}", template)
        self.assertNotIn("podman kube play", template)

    def test_native_log_destination_is_opt_in(self) -> None:
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
        template = Environment(undefined=StrictUndefined).from_string(
            (ROLE / "templates" / "kube.quadlet.j2").read_text()
        )
        values = dict(defaults, podman_systemd_description="Fixture",
                      podman_systemd_manifest_path="/private/pod.yml",
                      podman_systemd_after=[], podman_systemd_wants=[])
        self.assertNotIn("PodmanArgs=", template.render(**values))
        values["podman_systemd_log_path"] = "/private/application.log"
        rendered = template.render(**values)
        self.assertIn(
            "PodmanArgs=--log-driver=k8s-file --log-opt=path=/private/application.log",
            rendered,
        )
        self.assertEqual(rendered.count("PodmanArgs="), 1)

    def test_network_values_are_bounded_to_single_line_strings(self) -> None:
        tasks = yaml.safe_load(
            (ROLE / "tasks" / "assert.yml").read_text(encoding="utf-8")
        )
        assertions = tasks[0]["ansible.builtin.assert"]["that"]
        rendered = "\n".join(assertions)

        self.assertIn("podman_systemd_networks is sequence", assertions)
        self.assertIn("podman_systemd_networks is not string", assertions)
        self.assertIn("select('string')", rendered)
        self.assertIn("select('search', '[\\r\\n]')", rendered)

    def test_changed_quadlet_restarts_a_running_service(self) -> None:
        tasks = (ROLE / "tasks" / "main.yml").read_text(encoding="utf-8")

        self.assertIn("podman_systemd_quadlet_render.changed", tasks)
        self.assertIn("podman_systemd_action in ['present', 'started']", tasks)
        self.assertIn("'restarted'", tasks)


if __name__ == "__main__":
    unittest.main()
