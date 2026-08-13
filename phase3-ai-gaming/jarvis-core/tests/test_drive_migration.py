import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis_core.main import build_drive_inventory, build_drive_migration_plan


class DriveMigrationTests(unittest.TestCase):
    def test_inventory_groups_by_life_category_and_action(self):
        inventory = build_drive_inventory(
            [
                {
                    "id": "1",
                    "name": "EnMed interview prep",
                    "mime_type": "application/vnd.google-apps.document",
                },
                {
                    "id": "2",
                    "name": "Research poster abstract",
                    "mime_type": "application/pdf",
                },
                {
                    "id": "3",
                    "name": "Untitled form",
                    "mime_type": "application/vnd.google-apps.form",
                },
            ]
        )

        self.assertEqual(inventory["by_category"]["professional_education"], 1)
        self.assertEqual(inventory["by_category"]["research"], 1)
        self.assertEqual(inventory["by_category"]["needs_review"], 1)
        self.assertEqual(inventory["by_action"]["copy_to_homelab"], 2)
        self.assertEqual(inventory["by_action"]["needs_review"], 1)
        self.assertEqual(inventory["items"][0]["recommended_home"], "Docmost")
        self.assertIn("wiki pages", inventory["items"][0]["routing_reason"])

    def test_plan_builds_category_batches(self):
        inventory = build_drive_inventory(
            [
                {
                    "id": "1",
                    "name": "Work portfolio packet",
                    "mime_type": "application/vnd.google-apps.document",
                }
            ]
        )

        plan = build_drive_migration_plan(inventory)

        self.assertEqual(plan["summary"], "Metadata-only migration plan created. No files were downloaded or modified.")
        self.assertEqual(plan["suggested_batches"][0]["category"], "professional_work")
        self.assertFalse(plan["suggested_batches"][0]["current_scope_allows_copy"])
        self.assertNotIn("Zotero", str(plan["destination_map"]))
        self.assertNotIn("self-hosted Git", str(plan["destination_map"]))

    def test_code_items_route_to_github_reference_not_self_hosted_git(self):
        inventory = build_drive_inventory(
            [
                {
                    "id": "1",
                    "name": "GitHub repo code portfolio notes",
                    "mime_type": "application/vnd.google-apps.document",
                }
            ]
        )

        item = inventory["items"][0]

        self.assertEqual(item["recommended_home"], "GitHub reference")
        self.assertEqual(item["secondary_home"], "Nextcloud")
        self.assertIn("rather than self-hosting Git", item["routing_reason"])

    def test_items_include_copy_pathway_before_any_download(self):
        inventory = build_drive_inventory(
            [
                {
                    "id": "1",
                    "name": "Tax receipt",
                    "mime_type": "application/pdf",
                }
            ]
        )

        item = inventory["items"][0]

        self.assertEqual(item["recommended_home"], "Paperless")
        self.assertEqual(item["migration_action"], "copy_to_homelab")
        self.assertEqual(item["migration_pathway"][0]["status"], "available_now")
        self.assertEqual(item["migration_pathway"][2]["status"], "blocked_by_scope")


if __name__ == "__main__":
    unittest.main()
