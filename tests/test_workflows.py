from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class WorkflowSyntaxTests(unittest.TestCase):
    def test_all_workflows_are_valid_yaml_mappings(self):
        workflow_dir = ROOT / ".github" / "workflows"
        self.assertTrue(workflow_dir.exists(), "Workflows directory does not exist")
        workflows = list(workflow_dir.glob("*.yml"))
        self.assertGreater(len(workflows), 0, "No workflow YAML files found")

        for path in workflows:
            with self.subTest(path=path.name):
                parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(parsed, dict)
                self.assertIn("jobs", parsed)


if __name__ == "__main__":
    unittest.main()
