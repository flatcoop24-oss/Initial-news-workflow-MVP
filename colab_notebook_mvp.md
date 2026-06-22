# Colab 뉴스 요약 자동화 MVP

아래 코드는 Google Colab에서 **셀 단위로 그대로 붙여 넣어 실행**하는 기준입니다.

실행 흐름:

```text
API 키 설정
→ LLM Provider 설정
→ Gemini/OpenRouter/Groq 호출 함수 정의
→ CSV DB 함수 정의
→ 샘플 기사 요약
→ data/news.csv 저장
```

## Cell 1. API 키 설정

```python
"""
Colab Secrets 또는 직접 입력 방식으로 LLM API 키를 환경변수에 등록합니다.

권장 방식:
1. Colab 왼쪽 사이드바에서 Secrets를 엽니다.
2. GEMINI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY 이름으로 키를 저장합니다.
3. 아래 셀을 실행합니다.

주의:
- Groq API는 계정/크레딧 상태에 따라 무료 사용 가능 여부가 달라질 수 있습니다.
- 처음 MVP에서는 Gemini를 1순위, OpenRouter를 2순위, Groq을 3순위 fallback으로 둡니다.
"""

import os

try:
    from google.colab import userdata

    os.environ["GEMINI_API_KEY"] = userdata.get("GEMINI_API_KEY") or ""
    os.environ["OPENROUTER_API_KEY"] = userdata.get("OPENROUTER_API_KEY") or ""
    os.environ["GROQ_API_KEY"] = userdata.get("GROQ_API_KEY") or ""
except Exception:
    os.environ["GEMINI_API_KEY"] = os.environ.get("GEMINI_API_KEY", "")
    os.environ["OPENROUTER_API_KEY"] = os.environ.get("OPENROUTER_API_KEY", "")
    os.environ["GROQ_API_KEY"] = os.environ.get("GROQ_API_KEY", "")

print("Gemini key loaded:", bool(os.environ.get("GEMINI_API_KEY")))
print("OpenRouter key loaded:", bool(os.environ.get("OPENROUTER_API_KEY")))
print("Groq key loaded:", bool(os.environ.get("GROQ_API_KEY")))
```

## Cell 2. 기본 설정

```python
"""
뉴스 요약 MVP에서 사용할 기본 설정값입니다.

LLM_CONFIG:
- fallback_order 순서대로 호출합니다.
- 앞 provider가 실패하거나 rate limit/quota 오류가 나면 다음 provider로 넘어갑니다.

CSV_PATH:
- Colab 런타임 안에 저장되는 CSV 파일 경로입니다.
- 런타임이 초기화되면 사라질 수 있으므로, 나중에는 Google Drive 연동을 붙이면 좋습니다.
"""

from pathlib import Path

CSV_PATH = Path("data/news.csv")

LLM_CONFIG = {
    "fallback_order": ["gemini", "openrouter", "groq"],
    "providers": {
        "gemini": {
            "enabled": True,
            "model": "gemini-2.5-flash-lite",
        },
        "openrouter": {
            "enabled": True,
            "model": "nex-agi/nex-n2-pro:free",
            "site_url": "",
            "app_name": "news-summary-mvp",
        },
        "groq": {
            "enabled": True,
            "model": "llama-3.3-70b-versatile",
        },
    },
    "generation": {
        "temperature": 0.2,
        "max_tokens": 700,
    },
}
```

## Cell 3. LLM 라우터 함수

```python
"""
Gemini, OpenRouter, Groq API를 호출하고 자동 fallback을 처리하는 함수 모음입니다.

핵심 함수:
- summarize_news(title, content): 뉴스 제목/본문을 받아 요약 결과를 반환합니다.
- call_with_fallback(prompt, config): 설정된 provider 순서대로 호출합니다.
- parse_json_content(content): LLM 응답 문자열을 Python dict로 변환합니다.
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class LLMError(Exception):
    """LLM provider 호출 실패 정보를 담는 예외입니다."""

    def __init__(self, provider, message, status_code=None, retryable=False, quota_exhausted=False):
        """
        Args:
            provider: 실패한 provider 이름입니다. 예: gemini, openrouter, groq.
            message: 오류 메시지입니다.
            status_code: HTTP 상태 코드입니다. 없으면 None입니다.
            retryable: 재시도 가능한 오류인지 여부입니다.
            quota_exhausted: quota/rate limit/credit 소진으로 판단되는지 여부입니다.
        """
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable
        self.quota_exhausted = quota_exhausted


@dataclass
class LLMResult:
    """LLM 호출 성공 결과를 담는 데이터 클래스입니다."""

    provider: str
    model: str
    content: str
    raw: dict


def build_news_prompt(title, content):
    """
    뉴스 제목과 본문을 LLM 요약 프롬프트로 변환합니다.

    Args:
        title: 뉴스 제목입니다.
        content: 뉴스 본문 또는 기사 요약 원문입니다.

    Returns:
        LLM에 전달할 한국어 프롬프트 문자열입니다.
    """
    return f"""다음 뉴스 기사를 한국어로 요약해줘.

반드시 JSON만 출력해. 마크다운 코드블록은 쓰지 마.
형식:
{{
  "summary": "3문장 이내 요약",
  "category": "정책/경제/산업/기술/기업/국제/기타 중 하나",
  "importance": 1,
  "reason": "중요도 판단 이유 한 문장"
}}

중요도는 1부터 5 사이 숫자로 판단해.

제목:
{title}

본문:
{content}
"""


def summarize_news(title, content, config=LLM_CONFIG):
    """
    뉴스 1건을 요약합니다.

    Gemini → OpenRouter → Groq 순서로 호출하며, 앞 provider가 실패하면 다음 provider로 넘어갑니다.

    Args:
        title: 뉴스 제목입니다.
        content: 뉴스 본문입니다.
        config: provider 설정 딕셔너리입니다.

    Returns:
        LLMResult 객체입니다.
    """
    prompt = build_news_prompt(title, content)
    return call_with_fallback(prompt, config)


def call_with_fallback(prompt, config):
    """
    설정된 fallback 순서대로 LLM provider를 호출합니다.

    Args:
        prompt: LLM에 전달할 최종 프롬프트입니다.
        config: fallback_order와 provider별 설정을 담은 딕셔너리입니다.

    Returns:
        첫 번째 성공 provider의 LLMResult입니다.

    Raises:
        RuntimeError: 모든 provider가 실패한 경우 발생합니다.
    """
    errors = []

    for provider in config["fallback_order"]:
        provider_config = config["providers"].get(provider, {})
        if not provider_config.get("enabled", False):
            continue

        try:
            if provider == "gemini":
                return call_gemini(prompt, provider_config, config["generation"])
            if provider == "openrouter":
                return call_openrouter(prompt, provider_config, config["generation"])
            if provider == "groq":
                return call_groq(prompt, provider_config, config["generation"])
        except LLMError as exc:
            errors.append({
                "provider": exc.provider,
                "status_code": exc.status_code,
                "message": str(exc),
                "quota_exhausted": exc.quota_exhausted,
            })
            status = exc.status_code or "no_status"
            reason = str(exc).replace("\n", " ")[:220]
            print(f"[fallback] {provider} failed ({status}) -> {reason}")
            continue

    raise RuntimeError(json.dumps({"message": "All LLM providers failed.", "errors": errors}, ensure_ascii=False))


def call_gemini(prompt, provider_config, generation_config):
    """
    Gemini API를 호출합니다.

    Args:
        prompt: 요약 프롬프트입니다.
        provider_config: Gemini 모델 설정입니다.
        generation_config: temperature, max_tokens 설정입니다.

    Returns:
        LLMResult 객체입니다.
    """
    api_key = require_env("GEMINI_API_KEY", "gemini")
    model = provider_config["model"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": generation_config.get("temperature", 0.2),
            "maxOutputTokens": generation_config.get("max_tokens", 700),
            "responseMimeType": "application/json",
        },
    }

    raw = post_json("gemini", url, payload)
    try:
        content = raw["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise LLMError("gemini", f"Unexpected Gemini response: {raw}", retryable=True) from exc

    return LLMResult(provider="gemini", model=model, content=content, raw=raw)


def call_openrouter(prompt, provider_config, generation_config):
    """
    OpenRouter Chat Completions API를 호출합니다.

    Args:
        prompt: 요약 프롬프트입니다.
        provider_config: OpenRouter 모델 및 헤더 설정입니다.
        generation_config: temperature, max_tokens 설정입니다.

    Returns:
        LLMResult 객체입니다.
    """
    api_key = require_env("OPENROUTER_API_KEY", "openrouter")
    model = provider_config["model"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider_config.get("site_url"):
        headers["HTTP-Referer"] = provider_config["site_url"]
    if provider_config.get("app_name"):
        headers["X-Title"] = provider_config["app_name"]

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You summarize news articles and return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": generation_config.get("temperature", 0.2),
        "max_tokens": generation_config.get("max_tokens", 700),
        "response_format": {"type": "json_object"},
    }

    raw = post_json("openrouter", "https://openrouter.ai/api/v1/chat/completions", payload, headers=headers)
    try:
        content = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError("openrouter", f"Unexpected OpenRouter response: {raw}", retryable=True) from exc

    return LLMResult(provider="openrouter", model=model, content=content, raw=raw)


def call_groq(prompt, provider_config, generation_config):
    """
    Groq Chat Completions API를 호출합니다.

    Args:
        prompt: 요약 프롬프트입니다.
        provider_config: Groq 모델 설정입니다.
        generation_config: temperature, max_tokens 설정입니다.

    Returns:
        LLMResult 객체입니다.
    """
    api_key = require_env("GROQ_API_KEY", "groq")
    model = provider_config["model"]
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You summarize news articles and return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": generation_config.get("temperature", 0.2),
        "max_tokens": generation_config.get("max_tokens", 700),
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    raw = post_json("groq", "https://api.groq.com/openai/v1/chat/completions", payload, headers=headers)
    try:
        content = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError("groq", f"Unexpected Groq response: {raw}", retryable=True) from exc

    return LLMResult(provider="groq", model=model, content=content, raw=raw)


def post_json(provider, url, payload, headers=None, retries=1):
    """
    JSON POST 요청을 보내고 JSON 응답을 반환합니다.

    Args:
        provider: 호출 provider 이름입니다.
        url: API endpoint URL입니다.
        payload: 요청 body 딕셔너리입니다.
        headers: HTTP headers 딕셔너리입니다.
        retries: 재시도 횟수입니다.

    Returns:
        API 응답 JSON을 Python dict로 변환한 값입니다.

    Raises:
        LLMError: HTTP 오류, 네트워크 오류, quota/rate limit 오류가 발생한 경우입니다.
    """
    headers = headers or {"Content-Type": "application/json"}
    data = json.dumps(payload).encode("utf-8")

    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            body = exc.read().decode("utf-8", errors="replace")
            quota_exhausted = status_code in (402, 429) or "quota" in body.lower() or "rate" in body.lower()
            retryable = status_code in (408, 409, 425, 429, 500, 502, 503, 504)

            if retryable and attempt < retries:
                time.sleep(1 + attempt)
                continue

            raise LLMError(
                provider,
                f"HTTP {status_code}: {body[:500]}",
                status_code=status_code,
                retryable=retryable,
                quota_exhausted=quota_exhausted,
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < retries:
                time.sleep(1 + attempt)
                continue

            raise LLMError(provider, f"Network error: {exc}", retryable=True) from exc


def require_env(name, provider):
    """
    필수 환경변수를 읽습니다.

    Args:
        name: 환경변수 이름입니다.
        provider: 해당 환경변수를 사용하는 provider 이름입니다.

    Returns:
        환경변수 값입니다.

    Raises:
        LLMError: 환경변수가 비어 있는 경우입니다.
    """
    value = os.getenv(name)
    if not value:
        raise LLMError(provider, f"Missing environment variable: {name}")
    return value


def parse_json_content(content):
    """
    LLM 응답 문자열을 JSON dict로 변환합니다.

    Args:
        content: LLM이 반환한 문자열입니다.

    Returns:
        Python dict입니다.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    return json.loads(text)
```

## Cell 4. CSV DB 함수

```python
"""
뉴스 기사와 요약 결과를 CSV 파일에 저장하는 함수 모음입니다.

핵심 함수:
- ensure_news_csv(csv_path): CSV 파일과 헤더를 생성합니다.
- summarize_article(article, csv_path): 기사 1건을 요약하고 CSV에 저장합니다.
- load_existing_urls(csv_path): 중복 URL 체크용 URL set을 반환합니다.
"""

import csv
import hashlib
from datetime import datetime, timezone


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


def ensure_news_csv(csv_path=CSV_PATH):
    """
    뉴스 저장용 CSV 파일을 준비합니다.

    Args:
        csv_path: CSV 파일 경로입니다.

    Returns:
        Path 객체로 변환된 CSV 파일 경로입니다.
    """
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    if not csv_path.exists():
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=NEWS_FIELDS)
            writer.writeheader()

    return csv_path


def load_existing_urls(csv_path=CSV_PATH, success_only=False):
    """
    CSV에 이미 저장된 URL 목록을 불러옵니다.

    Args:
        csv_path: CSV 파일 경로입니다.
        success_only: success row의 URL만 중복으로 볼지 여부입니다.

    Returns:
        중복 체크에 사용할 URL set입니다.
    """
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
    """
    기사 URL 또는 제목을 기반으로 짧은 고유 ID를 만듭니다.

    Args:
        url: 기사 URL입니다.
        title: 기사 제목입니다.

    Returns:
        16자리 해시 문자열입니다.
    """
    base = url or title
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def now_iso():
    """
    현재 시각을 ISO 8601 문자열로 반환합니다.

    Returns:
        timezone 정보가 포함된 현재 시각 문자열입니다.
    """
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def build_base_row(article):
    """
    article 딕셔너리를 CSV 저장 row 형태로 변환합니다.

    Args:
        article: 뉴스 기사 정보 딕셔너리입니다.

    Returns:
        CSV 컬럼에 맞춘 row 딕셔너리입니다.
    """
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


def append_row(row, csv_path=CSV_PATH):
    """
    row 1개를 CSV 파일 끝에 추가합니다.

    Args:
        row: 저장할 row 딕셔너리입니다.
        csv_path: CSV 파일 경로입니다.

    Returns:
        CSV 컬럼 순서로 정규화된 row 딕셔너리입니다.
    """
    csv_path = ensure_news_csv(csv_path)
    normalized = {field: row.get(field, "") for field in NEWS_FIELDS}

    with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NEWS_FIELDS)
        writer.writerow(normalized)

    return normalized


def read_rows(csv_path=CSV_PATH):
    """
    CSV에 저장된 모든 row를 읽습니다.

    Args:
        csv_path: CSV 파일 경로입니다.

    Returns:
        row 딕셔너리 리스트입니다.
    """
    csv_path = ensure_news_csv(csv_path)
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_rows(rows, csv_path=CSV_PATH):
    """
    row 목록 전체를 CSV에 다시 씁니다.

    Args:
        rows: 저장할 row 딕셔너리 리스트입니다.
        csv_path: CSV 파일 경로입니다.

    Returns:
        저장한 row 딕셔너리 리스트입니다.
    """
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NEWS_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in NEWS_FIELDS})

    return rows


def collect_article(article, csv_path=CSV_PATH, skip_duplicates=True):
    """
    기사 1건을 요약하지 않고 pending 상태로 CSV에 저장합니다.

    Args:
        article: title, url, content 등을 포함한 기사 딕셔너리입니다.
        csv_path: 저장할 CSV 파일 경로입니다.
        skip_duplicates: URL이 이미 저장되어 있으면 건너뛸지 여부입니다.

    Returns:
        저장된 row 딕셔너리입니다.
    """
    csv_path = ensure_news_csv(csv_path)
    row = build_base_row(article)

    if skip_duplicates and row["url"] and row["url"] in load_existing_urls(csv_path):
        row["llm_status"] = "skipped"
        row["llm_error"] = "duplicate_url"
        return row

    append_row(row, csv_path)
    return row


def collect_articles(articles, csv_path=CSV_PATH, skip_duplicates=True):
    """
    여러 기사를 요약하지 않고 pending 상태로 CSV에 저장합니다.

    Args:
        articles: article 딕셔너리 리스트입니다.
        csv_path: 저장할 CSV 파일 경로입니다.
        skip_duplicates: URL이 이미 저장되어 있으면 건너뛸지 여부입니다.

    Returns:
        저장 또는 스킵된 row 딕셔너리 리스트입니다.
    """
    results = []
    for article in articles:
        results.append(collect_article(article, csv_path=csv_path, skip_duplicates=skip_duplicates))
    return results


def summarize_article(article, csv_path=CSV_PATH, skip_duplicates=True, skip_success_only=True):
    """
    기사 1건을 요약하고 CSV에 저장합니다.

    Args:
        article: title, url, content 등을 포함한 기사 딕셔너리입니다.
        csv_path: 저장할 CSV 파일 경로입니다.
        skip_duplicates: URL이 이미 저장되어 있으면 건너뛸지 여부입니다.
        skip_success_only: 성공한 URL만 중복으로 보고, failed URL은 재시도할지 여부입니다.

    Returns:
        요약 결과와 저장 상태가 포함된 row 딕셔너리입니다.
    """
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


def summarize_articles(articles, csv_path=CSV_PATH):
    """
    여러 기사 목록을 순서대로 요약하고 CSV에 저장합니다.

    Args:
        articles: article 딕셔너리 리스트입니다.
        csv_path: 저장할 CSV 파일 경로입니다.

    Returns:
        row 딕셔너리 리스트입니다.
    """
    results = []
    for article in articles:
        results.append(summarize_article(article, csv_path=csv_path))
    return results


def summarize_pending_rows(csv_path=CSV_PATH, limit=5):
    """
    CSV에 pending 또는 failed 상태로 남아 있는 기사 일부를 요약합니다.

    Args:
        csv_path: CSV 파일 경로입니다.
        limit: 이번 실행에서 요약할 최대 row 수입니다.

    Returns:
        업데이트된 전체 row 리스트입니다.
    """
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
```

## Cell 5. RSS 수집 함수

```python
"""
RSS/Atom feed에서 기사 목록을 가져와 article 딕셔너리 리스트로 변환합니다.

외부 패키지 없이 Colab 기본 파이썬 라이브러리만 사용합니다.
기본 feed는 Google News RSS 검색입니다.
"""

import html
import re
import urllib.request
import xml.etree.ElementTree as ET


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
        summarize_articles()에 바로 넣을 수 있는 article 딕셔너리 리스트입니다.
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
```

## Cell 6. RSS 기사 가져오기

```python
"""
RSS feed에서 기사 목록을 가져옵니다.

처음 테스트할 때는 limit_per_feed를 1~3 정도로 낮게 두는 것을 권장합니다.
요약 API 호출 비용과 무료 한도 소진을 줄이기 위해서입니다.
"""

articles = fetch_rss_articles(limit_per_feed=2)
print("수집 기사 수:", len(articles))
articles[:2]
```

## Cell 7. RSS 기사 CSV 저장

```python
"""
RSS에서 가져온 기사들을 요약 없이 CSV에 먼저 저장합니다.

이 셀이 성공하면 다음이 확인됩니다.
- RSS 수집
- CSV 저장

LLM API 한도가 없어도 이 단계는 계속 사용할 수 있습니다.
"""

ensure_news_csv(CSV_PATH)
rows = collect_articles(articles, csv_path=CSV_PATH)
rows[:3]
```

## Cell 8. pending 기사 요약

```python
"""
CSV에 pending 상태로 저장된 기사 중 일부만 요약합니다.

API 한도가 소진된 상태라면 이 셀은 건너뛰면 됩니다.
한도가 돌아오면 limit 값을 3, 10, 30처럼 천천히 늘립니다.
"""

rows = summarize_pending_rows(csv_path=CSV_PATH, limit=3)
rows[:3]
```

## Cell 9. 실패 원인 확인

```python
"""
요약이 실패했을 때 실제 원인을 확인합니다.

자주 나오는 원인:
- Missing environment variable: Colab Secrets 이름이 다르거나 노트북 접근 권한이 꺼져 있음
- HTTP 401/403: API 키가 잘못됐거나 권한이 없음
- HTTP 404: 모델명이 provider에서 지원되지 않음
- HTTP 429: 무료 한도 또는 rate limit 초과
- HTTP 400: 요청 형식 또는 response_format 옵션을 모델이 지원하지 않음
"""

stored_rows = read_rows(CSV_PATH)
failed_rows = [row for row in stored_rows if row.get("llm_status") == "failed"]
print("failed rows:", len(failed_rows))

if failed_rows:
    print(failed_rows[0].get("llm_error", "")[:2000])
```

## Cell 10. Provider 1회 진단

```python
"""
RSS 전체 요약 전에 기사 1건만 넣어서 provider 오류를 짧게 확인합니다.

이 셀에서 Gemini/OpenRouter/Groq 중 하나라도 성공하면 라우터는 정상입니다.
모두 실패하면 출력되는 HTTP 상태 코드와 메시지를 보고 키/모델/한도 문제를 고치면 됩니다.
"""

debug_article = {
    "published_at": "",
    "source": "debug",
    "title": "테스트 기사",
    "url": "https://example.com/debug-news",
    "keyword": "debug",
    "content": "AI 산업 투자와 반도체 수요가 증가하고 있다는 내용의 테스트 기사입니다.",
}

debug_row = summarize_article(debug_article, csv_path=CSV_PATH, skip_duplicates=False)
debug_row
```

## Cell 11. CSV 확인

```python
"""
저장된 CSV를 pandas DataFrame으로 확인합니다.

확인할 주요 컬럼:
- title: 기사 제목
- summary: 요약문
- category: 자동 분류 카테고리
- importance: 중요도
- llm_provider: 실제로 성공한 provider
- llm_status: success, failed, skipped 중 하나
"""

import pandas as pd

df = pd.read_csv(CSV_PATH)
df[["title", "summary", "category", "importance", "llm_provider", "llm_model", "llm_status"]]
```

## Cell 12. Markdown 리포트 생성

```python
"""
CSV에 저장된 기사로 Markdown 리포트를 생성합니다.

요약이 없는 pending 기사도 RSS content를 사용해서 리포트에 포함합니다.
"""

from collections import defaultdict
from datetime import datetime


def generate_markdown_report(rows, title=None, max_items=50):
    """
    뉴스 row 목록으로 Markdown 리포트를 생성합니다.

    Args:
        rows: 뉴스 row 딕셔너리 리스트입니다.
        title: 리포트 제목입니다.
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


stored_rows = read_rows(CSV_PATH)
markdown = generate_markdown_report(stored_rows, max_items=30)

Path("reports").mkdir(exist_ok=True)
report_path = Path("reports") / f"daily_{datetime.now().strftime('%Y-%m-%d')}.md"
report_path.write_text(markdown, encoding="utf-8")

print(report_path)
print(markdown[:1000])
```

## Cell 13. 직접 기사 넣기

```python
"""
직접 기사 데이터를 넣어 테스트합니다.

나중에 뉴스 API를 붙이면 API 응답을 이 article 형식으로 변환해서 summarize_article()에 넣으면 됩니다.
"""

article = {
    "published_at": "",
    "source": "직접입력",
    "title": "테스트 기사 제목",
    "url": "https://example.com/my-test-news-001",
    "keyword": "테스트",
    "content": "여기에 기사 본문을 넣습니다. 본문이 길수록 요약 품질이 좋아집니다.",
}

row = summarize_article(article, csv_path=CSV_PATH)
row
```

## Cell 14. 다음 단계 미리보기

```python
"""
다음 단계에서는 RSS feed 목록을 키워드별로 늘리거나 Google Drive 저장을 붙입니다.

목표 형태:
articles = [
    {
        "published_at": "...",
        "source": "...",
        "title": "...",
        "url": "...",
        "keyword": "...",
        "content": "...",
    }
]

그 다음 아래 한 줄로 전체 요약/저장이 가능합니다.
"""

# rows = summarize_articles(articles, csv_path=CSV_PATH)
```
