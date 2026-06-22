import argparse
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "llm_config.json"


class LLMError(Exception):
    def __init__(self, provider, message, status_code=None, retryable=False, quota_exhausted=False):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable
        self.quota_exhausted = quota_exhausted


@dataclass
class LLMResult:
    provider: str
    model: str
    content: str
    raw: dict


def load_config(path=DEFAULT_CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def summarize_news(title, content, config_path=DEFAULT_CONFIG_PATH):
    config = load_config(config_path)
    prompt = build_news_prompt(title, content)
    return call_with_fallback(prompt, config)


def call_with_fallback(prompt, config):
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


def build_news_prompt(title, content):
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


def call_gemini(prompt, provider_config, generation_config):
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
    value = os.getenv(name)
    if not value:
        raise LLMError(provider, f"Missing environment variable: {name}")
    return value


def parse_json_content(content):
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    return json.loads(text)


def main():
    parser = argparse.ArgumentParser(description="Test LLM fallback routing for news summaries.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--content", required=True)
    args = parser.parse_args()

    result = summarize_news(args.title, args.content)
    parsed = parse_json_content(result.content)
    print(json.dumps({
        "provider": result.provider,
        "model": result.model,
        "result": parsed,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
