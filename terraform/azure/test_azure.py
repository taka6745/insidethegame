"""`./dev azure` without Azure: the toolbox is faked and its calls recorded."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import azure


class PlanTests(unittest.TestCase):
    def test_plan_passes_the_stream_start_url_to_the_app_as_up_does(self):
        plans = {}

        def tool(args, *, workdir="/repo", env=None, capture=False, **_):
            if args[:2] == ["terraform", "plan"]:
                plans[workdir] = (args, env or {})
            if args[:2] == ["terraform", "output"]:
                return json.dumps({"stream_start_webhook_url": {"value": "https://guard/hook?token=secret"}})
            return ""

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(azure, "STATE", Path(tmp)), \
                mock.patch.object(azure, "tool", tool), mock.patch.object(azure, "say"), mock.patch("builtins.print"):
            for name in ("guard", *azure.STACKS):
                (Path(tmp) / name).mkdir()
                (Path(tmp) / name / "terraform.tfstate").write_text("{}")
            azure.plan({"subscription": "sub", "email": "ops@example.com"})
        self.assertEqual(plans["/repo/terraform"][1].get("TF_VAR_stream_start_url"), "https://guard/hook?token=secret")
        self.assertEqual([d for d, (_, env) in plans.items() if "TF_VAR_stream_start_url" in env], ["/repo/terraform"])
        self.assertFalse(any("secret" in a for args, _ in plans.values() for a in args))  # never on the command line
        # The demo build: seeds everywhere, demo control (and the public /demo-api/) in the app stack only.
        self.assertIn("-var=demo_control=true", plans["/repo/terraform"][0])
        self.assertNotIn("-var=demo_control=true", plans["/repo/etl/infra"][0])
        self.assertIn("-var=demo_seeds=true", plans["/repo/etl/infra"][0])

    def test_a_release_turns_demo_control_and_seeds_off(self):
        stack = azure.Stack("app", {"subscription": "sub", "release": True})
        self.assertIn("-var=demo_control=false", stack.variables())
        self.assertIn("-var=demo_seeds=false", stack.variables())


class EdgeProxyTests(unittest.TestCase):
    def test_up_points_the_edge_proxy_at_the_new_web_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "wrangler.toml"
            config.write_text('name = "edge"\nUPSTREAM = "https://old.example"\n')
            self.assertTrue(azure.point_edge_proxy("https://new.example/", config))
            self.assertEqual(config.read_text(), 'name = "edge"\nUPSTREAM = "https://new.example"\n')
            self.assertFalse(azure.point_edge_proxy("https://new.example", config))  # unchanged: nothing to redeploy

if __name__ == "__main__":
    unittest.main()
