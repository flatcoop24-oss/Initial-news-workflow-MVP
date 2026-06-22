# Colab 빌드업 순서

## Cell 1. 파일 업로드 확인

`scripts/`, `config/`, `colab_api_call_mvp.py`를 Colab 작업 폴더에 올린 뒤 실행합니다.

```python
from pathlib import Path

print(Path("scripts/llm_router.py").exists())
print(Path("scripts/csv_pipeline.py").exists())
print(Path("config/llm_config.json").exists())
```

## Cell 2. API 키 연결

Colab 왼쪽 Secrets에 아래 이름으로 키를 등록합니다.

```text
GEMINI_API_KEY
OPENROUTER_API_KEY
GROQ_API_KEY
```

그 다음 셀에서 불러옵니다.

```python
import os
from google.colab import userdata

os.environ["GEMINI_API_KEY"] = userdata.get("GEMINI_API_KEY") or ""
os.environ["OPENROUTER_API_KEY"] = userdata.get("OPENROUTER_API_KEY") or ""
os.environ["GROQ_API_KEY"] = userdata.get("GROQ_API_KEY") or ""
```

## Cell 3. CSV 초기화

```python
from pathlib import Path
from scripts.csv_pipeline import ensure_news_csv

csv_path = Path("data/news.csv")
ensure_news_csv(csv_path)
print(csv_path)
```

## Cell 4. RSS 기사 가져오기

```python
from scripts.rss_fetcher import fetch_rss_articles

articles = fetch_rss_articles(limit_per_feed=2)
print(len(articles))
articles[:2]
```

## Cell 5. RSS 기사 CSV 저장

```python
from scripts.csv_pipeline import collect_articles

rows = collect_articles(articles, csv_path=csv_path)
rows[:3]
```

## Cell 6. pending 기사 요약

API 한도가 없으면 이 셀은 건너뛰고, 수집/저장만 계속 진행해도 됩니다.

```python
from scripts.csv_pipeline import summarize_pending_rows

rows = summarize_pending_rows(csv_path=csv_path, limit=3)
rows[:3]
```

## Cell 7. CSV 확인

```python
import pandas as pd

df = pd.read_csv(csv_path)
df[["title", "summary", "category", "importance", "llm_provider", "llm_status"]]
```

## Cell 8. Markdown 리포트 생성

```python
from scripts.report_generator import generate_markdown_report, save_markdown_report
from scripts.csv_pipeline import read_rows

rows = read_rows(csv_path)
markdown = generate_markdown_report(rows, max_items=30)
report_path = save_markdown_report(markdown)
print(report_path)
print(markdown[:1000])
```

## Cell 9. 직접 기사 넣어보기

```python
from scripts.csv_pipeline import summarize_article

article = {
    "published_at": "",
    "source": "직접입력",
    "title": "테스트 기사 제목",
    "url": "https://example.com/my-test-news-001",
    "keyword": "테스트",
    "content": "여기에 기사 본문을 넣습니다. 본문이 길수록 요약 품질이 좋아집니다.",
}

row = summarize_article(article, csv_path=csv_path)
row
```

## 다음 단계

다음 빌드업에서는 `article` 딕셔너리를 직접 쓰는 대신 뉴스 검색 API에서 받아온 결과를 같은 형태로 변환합니다.
