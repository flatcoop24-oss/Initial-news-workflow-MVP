import argparse
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CSV_PATH = ROOT_DIR / "data" / "news.csv"
DEFAULT_REPORT_DIR = ROOT_DIR / "reports"


def load_news_rows(csv_path=DEFAULT_CSV_PATH):
    """
    CSV에 저장된 뉴스 row를 불러옵니다.

    Args:
        csv_path: 뉴스 CSV 파일 경로입니다.

    Returns:
        CSV row 딕셔너리 리스트입니다.
    """
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def generate_markdown_report(rows, title=None, max_items=50):
    """
    뉴스 row 목록으로 Markdown 리포트를 생성합니다.

    Args:
        rows: 뉴스 row 딕셔너리 리스트입니다.
        title: 리포트 제목입니다. 없으면 오늘 날짜 기반으로 생성합니다.
        max_items: 리포트에 포함할 최대 기사 수입니다.

    Returns:
        Markdown 문자열입니다.
    """
    title = title or f"뉴스 수집 리포트 - {datetime.now().strftime('%Y-%m-%d')}"
    grouped = defaultdict(list)

    for row in rows[:max_items]:
        key = row.get("keyword") or "기타"
        grouped[key].append(row)

    lines = [f"# {title}", ""]
    lines.append(f"- 전체 기사 수: {len(rows)}")
    lines.append(f"- 리포트 포함 기사 수: {min(len(rows), max_items)}")
    lines.append("")

    for keyword, items in grouped.items():
        lines.append(f"## {keyword}")
        lines.append("")
        for row in items:
            summary = row.get("summary") or row.get("content") or "요약 대기"
            status = row.get("llm_status") or "pending"
            source = row.get("source") or "unknown"
            title_text = row.get("title") or "(제목 없음)"
            url = row.get("url") or ""

            lines.append(f"- [{title_text}]({url})")
            lines.append(f"  - 출처: {source}")
            lines.append(f"  - 상태: {status}")
            lines.append(f"  - 내용: {summary}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def save_markdown_report(markdown, report_dir=DEFAULT_REPORT_DIR, filename=None):
    """
    Markdown 리포트를 파일로 저장합니다.

    Args:
        markdown: 저장할 Markdown 문자열입니다.
        report_dir: 리포트 저장 폴더입니다.
        filename: 저장 파일명입니다. 없으면 날짜 기반으로 생성합니다.

    Returns:
        저장된 Path 객체입니다.
    """
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    filename = filename or f"daily_{datetime.now().strftime('%Y-%m-%d')}.md"
    path = report_dir / filename
    path.write_text(markdown, encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description="Generate a Markdown report from news.csv.")
    parser.add_argument("--csv-path", default=str(DEFAULT_CSV_PATH))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--max-items", type=int, default=50)
    args = parser.parse_args()

    rows = load_news_rows(args.csv_path)
    markdown = generate_markdown_report(rows, max_items=args.max_items)
    path = save_markdown_report(markdown, args.report_dir)
    print(path)


if __name__ == "__main__":
    main()
