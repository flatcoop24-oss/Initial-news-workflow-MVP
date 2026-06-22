import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT_DIR / "reports"
DEFAULT_NOTION_VERSION = "2026-03-11"
RICH_TEXT_LIMIT = 1900


class NotionError(Exception):
    """Notion API 호출 실패를 나타내는 예외입니다."""


def create_notion_page_from_markdown(
    markdown,
    title=None,
    parent_page_id=None,
    api_key=None,
    notion_version=None,
):
    """
    Markdown 문자열을 Notion 페이지로 생성합니다.

    Args:
        markdown: Notion 페이지 본문으로 보낼 Markdown 문자열입니다.
        title: 생성할 Notion 페이지 제목입니다.
        parent_page_id: 새 페이지를 만들 상위 Notion 페이지 ID입니다.
        api_key: Notion integration secret입니다.
        notion_version: Notion API version입니다.

    Returns:
        Notion API 응답 딕셔너리입니다.
    """
    api_key = api_key or require_env("NOTION_API_KEY")
    parent_page_id = parent_page_id or require_env("NOTION_PARENT_PAGE_ID")
    notion_version = notion_version or os.getenv("NOTION_VERSION", DEFAULT_NOTION_VERSION)
    title = title or f"뉴스 수집 리포트 - {datetime.now().strftime('%Y-%m-%d')}"

    payload = {
        "parent": {"page_id": parent_page_id},
        "properties": {
            "title": {
                "title": [{"text": {"content": title}}],
            }
        },
        "markdown": markdown,
    }

    return post_notion_json("/v1/pages", payload, api_key=api_key, notion_version=notion_version)


def upload_report_file(report_path, title=None, parent_page_id=None, api_key=None):
    """
    Markdown 리포트 파일을 읽어 Notion 페이지로 업로드합니다.

    Args:
        report_path: Markdown 리포트 파일 경로입니다.
        title: Notion 페이지 제목입니다.
        parent_page_id: 상위 Notion 페이지 ID입니다.
        api_key: Notion integration secret입니다.

    Returns:
        Notion API 응답 딕셔너리입니다.
    """
    report_path = Path(report_path)
    markdown = report_path.read_text(encoding="utf-8")
    title = title or report_path.stem.replace("_", " ")
    return create_notion_page_from_markdown(
        markdown,
        title=title,
        parent_page_id=parent_page_id,
        api_key=api_key,
    )


def upload_rows_to_database(rows, database_id=None, api_key=None, notion_version=None, limit=50):
    """
    뉴스 row 목록을 Notion 데이터베이스에 기사별 페이지로 업로드합니다.

    Args:
        rows: news.csv row 딕셔너리 리스트입니다.
        database_id: Notion database ID입니다.
        api_key: Notion integration secret입니다.
        notion_version: Notion API version입니다.
        limit: 업로드할 최대 row 수입니다.

    Returns:
        생성된 Notion page 응답 리스트입니다.
    """
    api_key = api_key or require_env("NOTION_API_KEY")
    database_id = database_id or require_env("NOTION_DATABASE_ID")
    notion_version = notion_version or os.getenv("NOTION_VERSION", DEFAULT_NOTION_VERSION)
    responses = []

    for row in rows[:limit]:
        payload = build_database_page_payload(row, database_id)
        responses.append(post_notion_json("/v1/pages", payload, api_key=api_key, notion_version=notion_version))

    return responses


def build_database_page_payload(row, database_id):
    """
    news.csv row를 Notion database page 생성 payload로 변환합니다.

    Notion 데이터베이스에는 아래 속성이 있어야 합니다.
    - 제목: Title
    - 날짜: Date
    - 키워드: Select
    - 출처: Rich text
    - URL: URL
    - 상태: Select
    - 요약: Rich text
    - 카테고리: Select
    - 중요도: Number
    - 원문: Rich text

    Args:
        row: news.csv row 딕셔너리입니다.
        database_id: Notion database ID입니다.

    Returns:
        Notion API page creation payload입니다.
    """
    title = row.get("title") or "(제목 없음)"
    summary = row.get("summary") or row.get("content") or ""
    importance = parse_number(row.get("importance"))

    properties = {
        "제목": {"title": [{"text": {"content": truncate_text(title, RICH_TEXT_LIMIT)}}]},
        "키워드": select_property(row.get("keyword")),
        "출처": rich_text_property(row.get("source")),
        "URL": {"url": row.get("url") or None},
        "상태": select_property(row.get("llm_status") or "pending"),
        "요약": rich_text_property(summary),
        "카테고리": select_property(row.get("category")),
        "원문": rich_text_property(row.get("content")),
    }

    if row.get("published_at"):
        properties["날짜"] = {"date": {"start": row.get("published_at")}}
    if importance is not None:
        properties["중요도"] = {"number": importance}

    return {
        "parent": {"database_id": database_id},
        "properties": properties,
    }


def rich_text_property(value):
    """
    문자열을 Notion rich_text 속성으로 변환합니다.

    Args:
        value: 원본 문자열입니다.

    Returns:
        Notion rich_text property 딕셔너리입니다.
    """
    text = truncate_text(value or "", RICH_TEXT_LIMIT)
    return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}


def select_property(value):
    """
    문자열을 Notion select 속성으로 변환합니다.

    Args:
        value: select 이름입니다.

    Returns:
        Notion select property 딕셔너리입니다.
    """
    value = (value or "").strip()
    return {"select": {"name": value}} if value else {"select": None}


def parse_number(value):
    """
    문자열 숫자를 float으로 변환합니다.

    Args:
        value: 숫자 또는 문자열입니다.

    Returns:
        float 또는 None입니다.
    """
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def truncate_text(value, limit):
    """
    Notion API 제한을 피하기 위해 텍스트를 자릅니다.

    Args:
        value: 원본 문자열입니다.
        limit: 최대 길이입니다.

    Returns:
        잘린 문자열입니다.
    """
    value = str(value or "")
    return value[:limit]


def post_notion_json(path, payload, api_key, notion_version=DEFAULT_NOTION_VERSION):
    """
    Notion API에 JSON POST 요청을 보냅니다.

    Args:
        path: Notion API path입니다. 예: /v1/pages.
        payload: 요청 body 딕셔너리입니다.
        api_key: Notion integration secret입니다.
        notion_version: Notion API version입니다.

    Returns:
        JSON 응답 딕셔너리입니다.

    Raises:
        NotionError: HTTP 오류 또는 네트워크 오류가 발생한 경우입니다.
    """
    url = f"https://api.notion.com{path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": notion_version,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise NotionError(f"Notion HTTP {exc.code}: {body[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise NotionError(f"Notion network error: {exc}") from exc


def require_env(name):
    """
    필수 환경변수를 읽습니다.

    Args:
        name: 환경변수 이름입니다.

    Returns:
        환경변수 값입니다.

    Raises:
        NotionError: 환경변수가 비어 있는 경우입니다.
    """
    value = os.getenv(name)
    if not value:
        raise NotionError(f"Missing environment variable: {name}")
    return value


def main():
    parser = argparse.ArgumentParser(description="Upload a Markdown report to Notion.")
    parser.add_argument("--report-path", required=True)
    parser.add_argument("--title", default="")
    args = parser.parse_args()

    response = upload_report_file(args.report_path, title=args.title or None)
    print(json.dumps({"id": response.get("id"), "url": response.get("url")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
