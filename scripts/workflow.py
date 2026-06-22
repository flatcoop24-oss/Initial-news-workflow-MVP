import argparse
import json
import sys
from collections import Counter
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.csv_pipeline import collect_articles, read_rows, summarize_pending_rows
from scripts.notion_exporter import upload_report_file
from scripts.report_generator import generate_markdown_report, save_markdown_report
from scripts.rss_fetcher import DEFAULT_FEEDS_CSV_PATH, fetch_rss_articles, load_rss_feeds


DEFAULT_CSV_PATH = ROOT_DIR / "data" / "news.csv"
DEFAULT_REPORT_DIR = ROOT_DIR / "reports"


def run_workflow(
    feeds_csv=DEFAULT_FEEDS_CSV_PATH,
    csv_path=DEFAULT_CSV_PATH,
    report_dir=DEFAULT_REPORT_DIR,
    limit_per_feed=10,
    summarize_limit=0,
    report_items=50,
    upload_to_notion=False,
):
    """
    뉴스 자동화 MVP 전체 워크플로우를 실행합니다.

    Args:
        feeds_csv: RSS feed 설정 CSV 경로입니다.
        csv_path: 뉴스 저장 CSV 경로입니다.
        report_dir: Markdown 리포트 저장 폴더입니다.
        limit_per_feed: feed별 RSS 수집 기사 수입니다.
        summarize_limit: 이번 실행에서 요약할 pending 기사 수입니다. 0이면 요약하지 않습니다.
        report_items: Markdown 리포트에 포함할 최대 기사 수입니다.
        upload_to_notion: True이면 생성된 Markdown 리포트를 Notion 페이지로 업로드합니다.

    Returns:
        실행 결과 요약 딕셔너리입니다.
    """
    feeds = load_rss_feeds(feeds_csv)
    articles = fetch_rss_articles(feeds=feeds, limit_per_feed=limit_per_feed)
    collected_rows = collect_articles(articles, csv_path=csv_path)

    if summarize_limit > 0:
        rows = summarize_pending_rows(csv_path=csv_path, limit=summarize_limit)
    else:
        rows = read_rows(csv_path)

    markdown = generate_markdown_report(rows, max_items=report_items)
    report_path = save_markdown_report(markdown, report_dir=report_dir)
    notion_page = None

    if upload_to_notion:
        notion_response = upload_report_file(report_path)
        notion_page = {
            "id": notion_response.get("id", ""),
            "url": notion_response.get("url", ""),
        }

    collected_status = Counter(row.get("llm_status", "") for row in collected_rows)
    stored_status = Counter(row.get("llm_status", "") for row in rows)

    return {
        "feeds": len(feeds),
        "fetched_articles": len(articles),
        "collected_rows": len(collected_rows),
        "collected_status": dict(collected_status),
        "stored_rows": len(rows),
        "stored_status": dict(stored_status),
        "csv_path": str(csv_path),
        "report_path": str(report_path),
        "notion_page": notion_page,
    }


def main():
    parser = argparse.ArgumentParser(description="Run the RSS news collection, optional summarization, and report workflow.")
    parser.add_argument("--feeds-csv", default=str(DEFAULT_FEEDS_CSV_PATH))
    parser.add_argument("--csv-path", default=str(DEFAULT_CSV_PATH))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--limit-per-feed", type=int, default=10)
    parser.add_argument("--summarize-limit", type=int, default=0)
    parser.add_argument("--report-items", type=int, default=50)
    parser.add_argument("--upload-to-notion", action="store_true")
    args = parser.parse_args()

    result = run_workflow(
        feeds_csv=args.feeds_csv,
        csv_path=args.csv_path,
        report_dir=args.report_dir,
        limit_per_feed=args.limit_per_feed,
        summarize_limit=args.summarize_limit,
        report_items=args.report_items,
        upload_to_notion=args.upload_to_notion,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
