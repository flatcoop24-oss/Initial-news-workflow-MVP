import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.notion_exporter import build_database_page_payload, create_notion_page_from_markdown, upload_report_file, upload_rows_to_database


class NotionExporterTest(unittest.TestCase):
    def test_create_notion_page_from_markdown_posts_expected_payload(self):
        with patch("scripts.notion_exporter.post_notion_json") as post_json:
            post_json.return_value = {"id": "page-id", "url": "https://notion.so/page-id"}

            response = create_notion_page_from_markdown(
                "# 리포트\n\n내용",
                title="테스트 리포트",
                parent_page_id="parent-id",
                api_key="secret",
            )

        self.assertEqual(response["id"], "page-id")
        path, payload = post_json.call_args.args[:2]
        self.assertEqual(path, "/v1/pages")
        self.assertEqual(payload["parent"]["page_id"], "parent-id")
        self.assertEqual(payload["properties"]["title"]["title"][0]["text"]["content"], "테스트 리포트")
        self.assertEqual(payload["markdown"], "# 리포트\n\n내용")

    def test_upload_report_file_uses_file_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "daily_2026-06-22.md"
            report_path.write_text("# 오늘 뉴스\n", encoding="utf-8")

            with patch("scripts.notion_exporter.create_notion_page_from_markdown") as create_page:
                create_page.return_value = {"id": "page-id"}
                upload_report_file(report_path, parent_page_id="parent-id", api_key="secret")

        markdown = create_page.call_args.args[0]
        self.assertEqual(markdown, "# 오늘 뉴스\n")

    def test_build_database_page_payload(self):
        row = {
            "title": "AI 뉴스",
            "published_at": "2026-06-22",
            "keyword": "AI",
            "source": "테스트",
            "url": "https://example.com",
            "llm_status": "pending",
            "summary": "요약",
            "category": "기술",
            "importance": "4",
            "content": "본문",
        }

        payload = build_database_page_payload(row, "database-id")

        self.assertEqual(payload["parent"]["database_id"], "database-id")
        self.assertEqual(payload["properties"]["제목"]["title"][0]["text"]["content"], "AI 뉴스")
        self.assertEqual(payload["properties"]["키워드"]["select"]["name"], "AI")
        self.assertEqual(payload["properties"]["중요도"]["number"], 4.0)

    def test_upload_rows_to_database_posts_each_row(self):
        rows = [{"title": "AI 뉴스", "url": "https://example.com"}]

        with patch("scripts.notion_exporter.post_notion_json") as post_json:
            post_json.return_value = {"id": "page-id"}
            responses = upload_rows_to_database(rows, database_id="database-id", api_key="secret")

        self.assertEqual(responses[0]["id"], "page-id")
        self.assertEqual(post_json.call_count, 1)


if __name__ == "__main__":
    unittest.main()
