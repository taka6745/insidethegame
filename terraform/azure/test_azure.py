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

if __name__ == "__main__":
    unittest.main()
