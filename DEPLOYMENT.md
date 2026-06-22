# 배포 가이드

이 MVP는 서버형 앱이 아니라 정기 실행 자동화입니다. 추천 배포 방식은 GitHub Actions입니다.

## 추천 배포 구조

```text
GitHub Repository
  ↓
GitHub Actions schedule
  ↓
scripts/workflow.py 실행
  ↓
data/news.csv 업데이트
  ↓
reports/daily_YYYY-MM-DD.md 생성
  ↓
자동 commit/push
```

## 1. GitHub에 repository 생성

로컬 프로젝트를 GitHub repository에 push합니다.

```bash
git init
git add .
git commit -m "Initial news workflow MVP"
git branch -M main
git remote add origin https://github.com/<username>/<repo>.git
git push -u origin main
```

이미 git repository라면 `remote add`와 `push`만 하면 됩니다.

## 2. GitHub Secrets 등록

GitHub repository에서:

```text
Settings
→ Secrets and variables
→ Actions
→ New repository secret
```

아래 이름으로 등록합니다.

```text
GEMINI_API_KEY
OPENROUTER_API_KEY
GROQ_API_KEY
NOTION_API_KEY
NOTION_PARENT_PAGE_ID
```

LLM 요약을 당장 쓰지 않을 거라면 secret 없이도 RSS 수집과 리포트 생성은 됩니다. 이 경우 workflow 입력의 `summarize_limit`을 `0`으로 둡니다.

Notion 업로드를 쓰지 않을 거라면 `NOTION_API_KEY`, `NOTION_PARENT_PAGE_ID`는 비워도 됩니다. 이 경우 workflow 입력의 `upload_to_notion`을 `false`로 둡니다.

## 3. 자동 실행 시간

`.github/workflows/news-workflow.yml`은 UTC 기준 매일 22:00에 실행됩니다.

한국 시간으로는 다음 날 오전 7시입니다.

```yaml
schedule:
  - cron: "0 22 * * *"
```

## 4. 수동 실행

GitHub repository에서:

```text
Actions
→ News Workflow
→ Run workflow
```

입력값:

```text
limit_per_feed: RSS feed별 수집 기사 수
summarize_limit: 이번 실행에서 요약할 pending 기사 수
report_items: 리포트 포함 기사 수
upload_to_notion: Notion 업로드 여부
```

API 한도가 없으면:

```text
summarize_limit = 0
```

API 한도가 돌아오면:

```text
summarize_limit = 5
```

Notion 업로드를 켜려면:

```text
upload_to_notion = true
```

## 5. 결과 확인

실행 후 repository에 아래 파일이 업데이트됩니다.

```text
data/news.csv
reports/daily_YYYY-MM-DD.md
```

## 6. 키워드 수정

RSS 키워드와 feed는 아래 파일에서 수정합니다.

```text
config/rss_feeds.csv
```

컬럼:

```csv
source,keyword,url
```

## 7. Notion 연동

Notion에서:

```text
Settings
→ Connections
→ Develop or manage integrations
→ New integration
```

integration secret을 복사해서 GitHub Secret `NOTION_API_KEY`에 저장합니다.

그다음 Notion에서 리포트를 쌓을 상위 페이지를 열고:

```text
...
→ Connections
→ 방금 만든 integration 초대
```

상위 페이지 URL에서 page ID를 복사해 GitHub Secret `NOTION_PARENT_PAGE_ID`에 저장합니다.

## 대안

Colab은 수동 실행과 실험에 좋지만, 정기 자동화에는 약합니다.

서버 배포가 필요해지면 다음 단계로 옮길 수 있습니다.

```text
GitHub Actions MVP
→ Google Drive 저장 연동
→ Slack/Email 발송
→ Cloud Run 또는 Lambda API화
```
