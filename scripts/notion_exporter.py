import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT_DIR / "reports"
DEFAULT_NOTION_VERSION = "2022-06-28"
RICH_TEXT_LIMIT = 1900
MAX_BLOCKS_PER_PAGE = 90


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
        "children": markdown_to_notion_blocks(markdown)[:MAX_BLOCKS_PER_PAGE],
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
    database = get_notion_json(
        f"/v1/databases/{urllib.parse.quote(database_id)}",
        api_key=api_key,
        notion_version=notion_version,
    )
    schema_properties = database.get("properties", {})
    responses = []

    for row in rows[:limit]:
        payload = build_database_page_payload(row, database_id, schema_properties=schema_properties)
        responses.append(post_notion_json("/v1/pages", payload, api_key=api_key, notion_version=notion_version))

    return responses


def markdown_to_notion_blocks(markdown):
    """
    간단한 Markdown 리포트를 Notion block 리스트로 변환합니다.

    지원 형식:
    - # 제목
    - ## 소제목
    - - 불릿
    - 일반 문단

    Args:
        markdown: Markdown 문자열입니다.

    Returns:
        Notion block 딕셔너리 리스트입니다.
    """
    blocks = []

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("# "):
            blocks.append(text_block("heading_1", line[2:].strip()))
        elif line.startswith("## "):
            blocks.append(text_block("heading_2", line[3:].strip()))
        elif line.startswith("- "):
            blocks.append(text_block("bulleted_list_item", strip_markdown_link(line[2:].strip())))
        else:
            blocks.append(text_block("paragraph", strip_markdown_link(line)))

    return blocks or [text_block("paragraph", "리포트 내용이 없습니다.")]


def text_block(block_type, text):
    """
    Notion 텍스트 block을 생성합니다.

    Args:
        block_type: paragraph, heading_1, heading_2, bulleted_list_item 중 하나입니다.
        text: block에 넣을 텍스트입니다.

    Returns:
        Notion block 딕셔너리입니다.
    """
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": [{"type": "text", "text": {"content": truncate_text(text, RICH_TEXT_LIMIT)}}],
        },
    }


def strip_markdown_link(text):
    """
    Markdown 링크 문법을 Notion에 안전한 일반 텍스트로 단순화합니다.

    Args:
        text: 원본 문자열입니다.

    Returns:
        링크 문법이 단순화된 문자열입니다.
    """
    # [title](url) -> title (url)
    import re

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)


def build_database_page_payload(row, database_id, schema_properties=None):
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

    if schema_properties:
        properties = build_schema_aware_properties(
            schema_properties=schema_properties,
            title=title,
            summary=summary,
            importance=importance,
            row=row,
        )
    else:
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

        notion_date = normalize_notion_date(row.get("published_at"))
        if notion_date:
            properties["날짜"] = {"date": {"start": notion_date}}
        if importance is not None:
            properties["중요도"] = {"number": importance}

    return {
        "parent": {"database_id": database_id},
        "properties": properties,
    }


def build_schema_aware_properties(schema_properties, title, summary, importance, row):
    """
    실제 Notion DB 속성 이름과 타입을 기준으로 page properties를 생성합니다.

    Args:
        schema_properties: Notion database properties 응답 딕셔너리입니다.
        title: 기사 제목입니다.
        summary: 기사 요약 또는 본문 일부입니다.
        importance: 중요도 숫자 또는 None입니다.
        row: news.csv row 딕셔너리입니다.

    Returns:
        Notion API page properties 딕셔너리입니다.
    """
    properties = {}

    title_name = find_property_name(schema_properties, ["제목", "Name", "이름", "Title"], "title")
    if not title_name:
        raise NotionError("Notion database needs a title property such as 제목, Name, or 이름.")
    properties[title_name] = {"title": [{"text": {"content": truncate_text(title, RICH_TEXT_LIMIT)}}]}

    add_schema_property(properties, schema_properties, ["날짜", "Date", "게시일", "발행일"], row.get("published_at"), "date")
    add_schema_property(properties, schema_properties, ["키워드", "Keyword", "keyword"], row.get("keyword"), "select")
    add_schema_property(properties, schema_properties, ["출처", "Source", "source"], row.get("source"), "rich_text")
    add_schema_property(properties, schema_properties, ["URL", "url", "링크"], row.get("url"), "url")
    add_schema_property(properties, schema_properties, ["상태", "Status", "status"], row.get("llm_status") or "pending", "select")
    add_schema_property(properties, schema_properties, ["요약", "Summary", "summary"], summary, "rich_text")
    add_schema_property(properties, schema_properties, ["카테고리", "Category", "category"], row.get("category"), "select")
    add_schema_property(properties, schema_properties, ["중요도", "Importance", "importance"], importance, "number")
    add_schema_property(properties, schema_properties, ["원문", "본문", "Content", "content"], row.get("content"), "rich_text")

    return properties


def find_property_name(schema_properties, candidates, expected_type=None):
    """
    후보 이름 또는 타입을 기준으로 Notion DB 속성명을 찾습니다.

    Args:
        schema_properties: Notion database properties 응답 딕셔너리입니다.
        candidates: 우선 탐색할 속성명 후보입니다.
        expected_type: 기대하는 Notion 속성 타입입니다.

    Returns:
        매칭된 속성명 또는 None입니다.
    """
    for name in candidates:
        if name in schema_properties:
            return name

    if expected_type:
        for name, info in schema_properties.items():
            if info.get("type") == expected_type:
                return name

    return None


def add_schema_property(properties, schema_properties, candidates, value, preferred_type):
    """
    실제 DB에 존재하는 속성에만 값을 추가합니다.

    Args:
        properties: 생성 중인 Notion properties 딕셔너리입니다.
        schema_properties: Notion database properties 응답 딕셔너리입니다.
        candidates: 속성명 후보입니다.
        value: 넣을 값입니다.
        preferred_type: 값에 가장 적합한 Notion 속성 타입입니다.
    """
    name = find_property_name(schema_properties, candidates)
    if not name:
        return

    notion_type = schema_properties.get(name, {}).get("type")
    prop = property_for_type(value, notion_type or preferred_type)
    if prop is not None:
        properties[name] = prop


def property_for_type(value, notion_type):
    """
    Notion 속성 타입에 맞는 property 값을 생성합니다.

    Args:
        value: 원본 값입니다.
        notion_type: Notion 속성 타입입니다.

    Returns:
        Notion property 딕셔너리 또는 None입니다.
    """
    if notion_type == "date":
        notion_date = normalize_notion_date(value)
        return {"date": {"start": notion_date}} if notion_date else None
    if notion_type == "select":
        return select_property(value)
    if notion_type == "rich_text":
        return rich_text_property(value)
    if notion_type == "url":
        return {"url": value or None}
    if notion_type == "number":
        number = parse_number(value)
        return {"number": number} if number is not None else None
    if notion_type == "status":
        value = (value or "").strip()
        return {"status": {"name": value}} if value else None
    return None


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


def normalize_notion_date(value):
    """
    RSS/ISO 날짜 문자열을 Notion Date 속성이 받을 수 있는 ISO 8601 문자열로 변환합니다.

    Args:
        value: 날짜 문자열입니다. 예: Mon, 22 Jun 2026 05:07:17 GMT 또는 2026-06-22.

    Returns:
        ISO 8601 날짜 문자열입니다. 변환할 수 없으면 None입니다.
    """
    value = (value or "").strip()
    if not value:
        return None

    try:
        if value.endswith("Z"):
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return value
        datetime.fromisoformat(value)
        return value
    except ValueError:
        pass

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None

    if parsed is None:
        return None
    return parsed.isoformat()


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


def get_notion_json(path, api_key, notion_version=DEFAULT_NOTION_VERSION):
    """
    Notion API에 JSON GET 요청을 보냅니다.

    Args:
        path: Notion API path입니다. 예: /v1/databases/{database_id}.
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
        "Notion-Version": notion_version,
    }
    request = urllib.request.Request(url, headers=headers, method="GET")

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
