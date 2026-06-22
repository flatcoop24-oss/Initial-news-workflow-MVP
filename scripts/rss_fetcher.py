import argparse
import csv
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FEEDS_CSV_PATH = ROOT_DIR / "config" / "rss_feeds.csv"


DEFAULT_RSS_FEEDS = [
    {
        "source": "Google News",
        "keyword": "AI",
        "url": "https://news.google.com/rss/search?q=AI&hl=ko&gl=KR&ceid=KR:ko",
    },
    {
        "source": "Google News",
        "keyword": "반도체",
        "url": "https://news.google.com/rss/search?q=%EB%B0%98%EB%8F%84%EC%B2%B4&hl=ko&gl=KR&ceid=KR:ko",
    },
]


def fetch_rss_articles(feeds=None, limit_per_feed=10):
    """
    RSS/Atom feed 목록에서 뉴스 기사 목록을 가져옵니다.

    Args:
        feeds: {"source", "keyword", "url"} 딕셔너리 리스트입니다.
        limit_per_feed: feed별 최대 수집 기사 수입니다.

    Returns:
        csv_pipeline.summarize_articles()에 바로 넣을 수 있는 article 딕셔너리 리스트입니다.
    """
    feeds = feeds or DEFAULT_RSS_FEEDS
    articles = []

    for feed in feeds:
        xml_text = download_text(feed["url"])
        root = ET.fromstring(xml_text)
        entries = parse_entries(root)

        for entry in entries[:limit_per_feed]:
            article = normalize_entry(entry, feed)
            if article["title"] and article["url"]:
                articles.append(article)

    return dedupe_articles(articles)


def load_rss_feeds(csv_path=DEFAULT_FEEDS_CSV_PATH):
    """
    RSS feed 설정 CSV를 읽습니다.

    Args:
        csv_path: source, keyword, url 컬럼을 가진 CSV 파일 경로입니다.

    Returns:
        {"source", "keyword", "url"} 딕셔너리 리스트입니다.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return DEFAULT_RSS_FEEDS

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        return [
            {"source": row.get("source", ""), "keyword": row.get("keyword", ""), "url": row.get("url", "")}
            for row in csv.DictReader(f)
            if row.get("url")
        ]


def download_text(url, timeout=30):
    """
    URL에서 텍스트 데이터를 다운로드합니다.

    Args:
        url: 다운로드할 RSS/Atom URL입니다.
        timeout: 요청 제한 시간입니다.

    Returns:
        UTF-8 문자열입니다.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 news-summary-mvp"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_entries(root):
    """
    XML root에서 RSS item 또는 Atom entry 요소를 찾습니다.

    Args:
        root: ElementTree XML root입니다.

    Returns:
        XML entry element 리스트입니다.
    """
    items = root.findall(".//item")
    if items:
        return items

    return root.findall(".//{http://www.w3.org/2005/Atom}entry")


def normalize_entry(entry, feed):
    """
    RSS item/Atom entry를 공통 article 딕셔너리로 변환합니다.

    Args:
        entry: RSS item 또는 Atom entry XML element입니다.
        feed: source, keyword 정보를 담은 feed 설정입니다.

    Returns:
        article 딕셔너리입니다.
    """
    title = clean_text(find_text(entry, ["title"]))
    link = find_link(entry)
    published_at = find_text(entry, ["pubDate", "published", "updated"])
    description = clean_text(find_text(entry, ["description", "summary", "content"]))

    return {
        "published_at": published_at,
        "source": feed.get("source", ""),
        "title": title,
        "url": link,
        "keyword": feed.get("keyword", ""),
        "content": description or title,
    }


def find_text(entry, names):
    """
    XML entry에서 주어진 태그 이름 중 먼저 발견되는 텍스트를 반환합니다.

    Args:
        entry: XML element입니다.
        names: 찾을 태그 이름 리스트입니다.

    Returns:
        텍스트 문자열입니다. 없으면 빈 문자열입니다.
    """
    for name in names:
        node = entry.find(name)
        if node is None:
            node = entry.find(f"{{http://www.w3.org/2005/Atom}}{name}")
        if node is not None and node.text:
            return node.text
    return ""


def find_link(entry):
    """
    XML entry에서 기사 링크를 찾습니다.

    Args:
        entry: XML element입니다.

    Returns:
        기사 URL 문자열입니다.
    """
    link_text = find_text(entry, ["link"])
    if link_text:
        return link_text

    atom_link = entry.find("{http://www.w3.org/2005/Atom}link")
    if atom_link is not None:
        return atom_link.attrib.get("href", "")

    return ""


def clean_text(text):
    """
    RSS description에 섞인 HTML 태그와 엔티티를 정리합니다.

    Args:
        text: 원본 텍스트입니다.

    Returns:
        정리된 일반 텍스트입니다.
    """
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def dedupe_articles(articles):
    """
    URL 기준으로 기사 목록 중복을 제거합니다.

    Args:
        articles: article 딕셔너리 리스트입니다.

    Returns:
        중복 URL이 제거된 article 리스트입니다.
    """
    seen = set()
    deduped = []

    for article in articles:
        url = article.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        deduped.append(article)

    return deduped


def main():
    parser = argparse.ArgumentParser(description="Fetch RSS news articles.")
    parser.add_argument("--feeds-csv", default=str(DEFAULT_FEEDS_CSV_PATH))
    parser.add_argument("--limit-per-feed", type=int, default=3)
    args = parser.parse_args()

    feeds = load_rss_feeds(args.feeds_csv)
    articles = fetch_rss_articles(feeds=feeds, limit_per_feed=args.limit_per_feed)
    print(json.dumps(articles, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
