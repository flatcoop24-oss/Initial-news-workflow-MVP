# 뉴스 요약 자동화 MVP

CSV 기반 뉴스 데이터베이스와 LLM API 호출을 결합한 뉴스 요약 자동화 MVP입니다.

## 최종 MVP 흐름

```text
config/rss_feeds.csv
  ↓
RSS 기사 수집
  ↓
data/news.csv에 pending 저장
  ↓
선택적으로 pending 기사 LLM 요약
  ↓
reports/daily_YYYY-MM-DD.md 생성
```

## LLM 호출 순서

현재 구현된 호출 순서:

1. Gemini
2. OpenRouter
3. Groq

앞 provider가 API 키 없음, quota/rate limit, HTTP 오류, 네트워크 오류 등으로 실패하면 다음 provider로 자동 전환합니다.

## 환경변수

```bash
export GEMINI_API_KEY="..."
export OPENROUTER_API_KEY="..."
export GROQ_API_KEY="..."
export NOTION_API_KEY="..."
export NOTION_PARENT_PAGE_ID="..."
```

Groq API는 무료 사용 가능 여부가 계정/크레딧 상태에 따라 달라질 수 있습니다.

## 로컬 테스트

```bash
python scripts/llm_router.py \
  --title "AI 반도체 수요 증가" \
  --content "AI 서비스 확산으로 고성능 반도체 수요가 늘고 있다."
```

샘플 기사를 요약해서 CSV에 저장:

```bash
python scripts/csv_pipeline.py
```

RSS 기사 목록 가져오기:

```bash
python scripts/rss_fetcher.py --limit-per-feed 3
```

API 한도와 관계없이 RSS 기사를 CSV에 먼저 저장한 뒤, 나중에 pending 기사만 요약할 수 있습니다.

```python
from scripts.csv_pipeline import collect_articles, summarize_pending_rows
from scripts.rss_fetcher import fetch_rss_articles

articles = fetch_rss_articles(limit_per_feed=10)
collect_articles(articles)

# LLM 한도가 돌아왔을 때
summarize_pending_rows(limit=5)
```

Markdown 리포트 생성:

```bash
python scripts/report_generator.py --max-items 50
```

전체 워크플로우 한 번에 실행:

```bash
python scripts/workflow.py --limit-per-feed 10 --summarize-limit 0 --report-items 50
```

LLM 한도가 돌아왔을 때 pending 기사 5개만 요약까지 실행:

```bash
python scripts/workflow.py --limit-per-feed 10 --summarize-limit 5 --report-items 50
```

Notion 페이지 업로드까지 실행:

```bash
python scripts/workflow.py --limit-per-feed 10 --summarize-limit 0 --report-items 50 --upload-to-notion
```

결과 파일:

```text
data/news.csv
reports/daily_YYYY-MM-DD.md
```

RSS 키워드와 feed는 `config/rss_feeds.csv`에서 수정합니다.

## Colab 테스트

`colab_api_call_mvp.py`, `scripts/`, `config/` 폴더를 Colab에 업로드한 뒤 실행합니다.

Colab Secrets를 쓰는 경우에는 `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY` 이름으로 등록하면 됩니다.

셀 단위로 따라가려면 `COLAB_STEPS.md`를 참고합니다.

코랩에 그대로 붙여 넣을 docstring 포함 버전은 `colab_notebook_mvp.md`를 참고합니다.

## 배포

추천 배포 방식은 GitHub Actions입니다.

```bash
python scripts/workflow.py --limit-per-feed 10 --summarize-limit 0 --report-items 50
```

위 명령을 매일 자동 실행하고 결과를 repository에 다시 commit하도록 `.github/workflows/news-workflow.yml`을 준비했습니다.

자세한 배포 절차는 `DEPLOYMENT.md`를 참고합니다.

## Notion 연동

GitHub Secrets에 아래 값을 추가합니다.

```text
NOTION_API_KEY
NOTION_PARENT_PAGE_ID
```

Notion에서 integration을 만든 뒤, 리포트를 생성할 상위 페이지에 해당 integration을 초대해야 합니다.

수동 실행 시 `upload_to_notion` 값을 `true`로 설정하면 Markdown 리포트를 Notion 페이지로 업로드합니다.
