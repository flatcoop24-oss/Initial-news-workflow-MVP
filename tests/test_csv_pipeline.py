import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.csv_pipeline import collect_article, ensure_news_csv, sample_articles, summarize_article, summarize_pending_rows
from scripts.llm_router import LLMResult


class CsvPipelineTest(unittest.TestCase):
    def test_creates_csv_and_appends_summary_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "news.csv"
            article = sample_articles()[0]

            with patch("scripts.csv_pipeline.summarize_news") as summarize_news:
                summarize_news.return_value = LLMResult(
                    provider="gemini",
                    model="gemini-test",
                    content='{"summary":"요약","category":"기술","importance":4,"reason":"중요"}',
                    raw={},
                )
                row = summarize_article(article, csv_path=csv_path)

            self.assertEqual(row["llm_status"], "success")
            self.assertEqual(row["summary"], "요약")

            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["llm_provider"], "gemini")

    def test_skips_duplicate_url_without_appending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "news.csv"
            article = sample_articles()[0]
            ensure_news_csv(csv_path)

            with patch("scripts.csv_pipeline.summarize_news") as summarize_news:
                summarize_news.return_value = LLMResult(
                    provider="gemini",
                    model="gemini-test",
                    content='{"summary":"요약","category":"기술","importance":4,"reason":"중요"}',
                    raw={},
                )
                summarize_article(article, csv_path=csv_path)
                duplicate = summarize_article(article, csv_path=csv_path)

            self.assertEqual(duplicate["llm_status"], "skipped")
            self.assertEqual(duplicate["llm_error"], "duplicate_url")

            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 1)

    def test_collect_article_saves_pending_without_llm_call(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "news.csv"
            article = sample_articles()[0]

            row = collect_article(article, csv_path=csv_path)

            self.assertEqual(row["llm_status"], "pending")
            self.assertEqual(row["summary"], "")

            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["llm_status"], "pending")

    def test_summarize_pending_rows_updates_existing_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "news.csv"
            article = sample_articles()[0]
            collect_article(article, csv_path=csv_path)

            with patch("scripts.csv_pipeline.summarize_news") as summarize_news:
                summarize_news.return_value = LLMResult(
                    provider="openrouter",
                    model="free-test",
                    content='{"summary":"나중 요약","category":"기술","importance":3,"reason":"재시도"}',
                    raw={},
                )
                rows = summarize_pending_rows(csv_path=csv_path, limit=1)

            self.assertEqual(rows[0]["llm_status"], "success")
            self.assertEqual(rows[0]["summary"], "나중 요약")


if __name__ == "__main__":
    unittest.main()
