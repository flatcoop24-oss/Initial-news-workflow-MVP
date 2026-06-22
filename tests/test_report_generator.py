import tempfile
import unittest
from pathlib import Path

from scripts.report_generator import generate_markdown_report, save_markdown_report


class ReportGeneratorTest(unittest.TestCase):
    def test_generate_markdown_report_uses_summary_or_content(self):
        rows = [
            {
                "keyword": "AI",
                "title": "AI 뉴스",
                "url": "https://example.com/ai",
                "source": "테스트",
                "summary": "",
                "content": "RSS 내용",
                "llm_status": "pending",
            }
        ]

        markdown = generate_markdown_report(rows, title="테스트 리포트")

        self.assertIn("# 테스트 리포트", markdown)
        self.assertIn("## AI", markdown)
        self.assertIn("RSS 내용", markdown)

    def test_save_markdown_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_markdown_report("# 테스트\n", report_dir=Path(tmpdir), filename="test.md")

            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(encoding="utf-8"), "# 테스트\n")


if __name__ == "__main__":
    unittest.main()
