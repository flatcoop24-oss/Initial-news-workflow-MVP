"""
Google Colab에서 위에서 아래로 실행하기 위한 MVP 예시입니다.

1. 이 파일과 scripts/, config/ 폴더를 Colab에 업로드합니다.
2. 왼쪽 Secrets 또는 os.environ으로 API 키를 설정합니다.
3. RSS 기사를 가져와 요약하고 data/news.csv에 저장합니다.
"""

import os
from pathlib import Path

from scripts.csv_pipeline import collect_articles, ensure_news_csv
from scripts.rss_fetcher import fetch_rss_articles


# Colab Secrets를 쓰는 경우:
# from google.colab import userdata
# os.environ["GEMINI_API_KEY"] = userdata.get("GEMINI_API_KEY")
# os.environ["OPENROUTER_API_KEY"] = userdata.get("OPENROUTER_API_KEY")
# os.environ["GROQ_API_KEY"] = userdata.get("GROQ_API_KEY")

os.environ["GEMINI_API_KEY"] = os.environ.get("GEMINI_API_KEY", "")
os.environ["OPENROUTER_API_KEY"] = os.environ.get("OPENROUTER_API_KEY", "")
os.environ["GROQ_API_KEY"] = os.environ.get("GROQ_API_KEY", "")


csv_path = Path("data/news.csv")
ensure_news_csv(csv_path)

articles = fetch_rss_articles(limit_per_feed=3)
rows = collect_articles(articles, csv_path=csv_path)

for row in rows:
    print("status:", row["llm_status"])
    print("provider:", row["llm_provider"])
    print("model:", row["llm_model"])
    print("summary:", row["summary"])
    print("csv:", csv_path)
