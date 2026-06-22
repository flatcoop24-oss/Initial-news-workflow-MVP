import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.workflow import run_workflow


class WorkflowTest(unittest.TestCase):
    def test_run_workflow_collects_and_generates_report_without_summarizing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            feeds_csv = tmpdir / "feeds.csv"
            csv_path = tmpdir / "news.csv"
            report_dir = tmpdir / "reports"
            feeds_csv.write_text("source,keyword,url\n테스트,AI,https://example.com/rss\n", encoding="utf-8")

            articles = [
                {
                    "published_at": "",
                    "source": "테스트",
                    "title": "AI 뉴스",
                    "url": "https://example.com/news/1",
                    "keyword": "AI",
                    "content": "AI 뉴스 내용",
                }
            ]

            with patch("scripts.workflow.fetch_rss_articles", return_value=articles):
                result = run_workflow(
                    feeds_csv=feeds_csv,
                    csv_path=csv_path,
                    report_dir=report_dir,
                    limit_per_feed=1,
                    summarize_limit=0,
                    report_items=10,
                )

            self.assertEqual(result["fetched_articles"], 1)
            self.assertEqual(result["stored_status"]["pending"], 1)
            self.assertTrue(csv_path.exists())
            self.assertTrue(Path(result["report_path"]).exists())


if __name__ == "__main__":
    unittest.main()
