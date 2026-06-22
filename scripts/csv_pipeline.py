import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.llm_router import parse_json_content, summarize_news

DEFAULT_CSV_PATH = ROOT_DIR / "data" / "news.csv"

NEWS_FIELDS = [
    "id",
    "collected_at",
    "published_at",
    "source",
    "title",
    "url",
    "keyword",
    "content",
    "summary",
    "category",
    "importance",
    "reason",
    "llm_provider",
    "llm_model",
    "llm_status",
    "llm_error",
]


def ensure_news_csv(csv_path=DEFAULT_CSV_PATH):
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not csv_path.exists():
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=NEWS_FIELDS)
            writer.writeheader()
    return csv_path


def load_existing_urls(csv_path=DEFAULT_CSV_PATH, success_only=False):
    csv_path = ensure_news_csv(csv_path)
    urls = set()
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if success_only and row.get("llm_status") != "success":
                continue
            if row.get("url"):
                urls.add(row["url"])
    return urls


def make_article_id(url, title):
    base = url or title
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def build_base_row(article):
    return {
        "id": make_article_id(article.get("url", ""), article.get("title", "")),
        "collected_at": now_iso(),
        "published_at": article.get("published_at", ""),
        "source": article.get("source", ""),
        "title": article.get("title", ""),
        "url": article.get("url", ""),
        "keyword": article.get("keyword", ""),
        "content": article.get("content", ""),
        "summary": "",
        "category": "",
        "importance": "",
        "reason": "",
        "llm_provider": "",
        "llm_model": "",
        "llm_status": "pending",
        "llm_error": "",
    }


def append_row(row, csv_path=DEFAULT_CSV_PATH):
    csv_path = ensure_news_csv(csv_path)
    normalized = {field: row.get(field, "") for field in NEWS_FIELDS}
    with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NEWS_FIELDS)
        writer.writerow(normalized)
    return normalized


def read_rows(csv_path=DEFAULT_CSV_PATH):
    csv_path = ensure_news_csv(csv_path)
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_rows(rows, csv_path=DEFAULT_CSV_PATH):
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NEWS_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in NEWS_FIELDS})
    return rows


def collect_article(article, csv_path=DEFAULT_CSV_PATH, skip_duplicates=True):
    csv_path = ensure_news_csv(csv_path)
    row = build_base_row(article)

    if skip_duplicates and row["url"] and row["url"] in load_existing_urls(csv_path):
        row["llm_status"] = "skipped"
        row["llm_error"] = "duplicate_url"
        return row

    append_row(row, csv_path)
    return row


def collect_articles(articles, csv_path=DEFAULT_CSV_PATH, skip_duplicates=True):
    results = []
    for article in articles:
        results.append(collect_article(article, csv_path=csv_path, skip_duplicates=skip_duplicates))
    return results


def summarize_article(article, csv_path=DEFAULT_CSV_PATH, skip_duplicates=True, skip_success_only=True):
    csv_path = ensure_news_csv(csv_path)
    row = build_base_row(article)

    existing_urls = load_existing_urls(csv_path, success_only=skip_success_only)
    if skip_duplicates and row["url"] and row["url"] in existing_urls:
        row["llm_status"] = "skipped"
        row["llm_error"] = "duplicate_url"
        return row

    try:
        result = summarize_news(row["title"], row["content"])
        parsed = parse_json_content(result.content)
        row.update({
            "summary": parsed.get("summary", ""),
            "category": parsed.get("category", ""),
            "importance": parsed.get("importance", ""),
            "reason": parsed.get("reason", ""),
            "llm_provider": result.provider,
            "llm_model": result.model,
            "llm_status": "success",
            "llm_error": "",
        })
    except Exception as exc:
        row["llm_status"] = "failed"
        row["llm_error"] = str(exc)[:1000]

    append_row(row, csv_path)
    return row


def summarize_articles(articles, csv_path=DEFAULT_CSV_PATH):
    results = []
    for article in articles:
        results.append(summarize_article(article, csv_path=csv_path))
    return results


def summarize_pending_rows(csv_path=DEFAULT_CSV_PATH, limit=5):
    rows = read_rows(csv_path)
    updated = []
    summarized_count = 0

    for row in rows:
        if summarized_count >= limit:
            updated.append(row)
            continue

        if row.get("llm_status") not in ("pending", "failed"):
            updated.append(row)
            continue

        try:
            result = summarize_news(row.get("title", ""), row.get("content", ""))
            parsed = parse_json_content(result.content)
            row.update({
                "summary": parsed.get("summary", ""),
                "category": parsed.get("category", ""),
                "importance": parsed.get("importance", ""),
                "reason": parsed.get("reason", ""),
                "llm_provider": result.provider,
                "llm_model": result.model,
                "llm_status": "success",
                "llm_error": "",
            })
        except Exception as exc:
            row["llm_status"] = "failed"
            row["llm_error"] = str(exc)[:1000]

        summarized_count += 1
        updated.append(row)

    write_rows(updated, csv_path)
    return updated


def sample_articles():
    return [
        {
            "published_at": "2026-06-22T09:00:00+09:00",
            "source": "샘플뉴스",
            "title": "AI 반도체 수요 증가로 주요 기업 투자 확대",
            "url": "https://example.com/news/ai-chip-investment",
            "keyword": "AI 반도체",
            "content": (
                "글로벌 AI 서비스 확산으로 고성능 반도체 수요가 늘어나면서 주요 기업들이 "
                "데이터센터와 AI 가속기 투자를 확대하고 있다. 업계는 공급망 안정성과 전력 비용이 "
                "향후 경쟁력의 핵심 변수가 될 것으로 보고 있다."
            ),
        }
    ]


def main():
    parser = argparse.ArgumentParser(description="Summarize sample news articles and save them to CSV.")
    parser.add_argument("--csv-path", default=str(DEFAULT_CSV_PATH))
    args = parser.parse_args()

    rows = summarize_articles(sample_articles(), csv_path=args.csv_path)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
