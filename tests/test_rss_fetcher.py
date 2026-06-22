import unittest
import xml.etree.ElementTree as ET

from scripts.rss_fetcher import clean_text, normalize_entry, parse_entries


class RssFetcherTest(unittest.TestCase):
    def test_parse_rss_item_to_article(self):
        xml = """
        <rss>
          <channel>
            <item>
              <title>AI 투자 확대</title>
              <link>https://example.com/news/1</link>
              <pubDate>Mon, 22 Jun 2026 09:00:00 +0900</pubDate>
              <description><![CDATA[<b>기업</b>들이 AI 투자를 늘리고 있다.]]></description>
            </item>
          </channel>
        </rss>
        """
        root = ET.fromstring(xml)
        entries = parse_entries(root)
        article = normalize_entry(entries[0], {"source": "테스트", "keyword": "AI"})

        self.assertEqual(article["title"], "AI 투자 확대")
        self.assertEqual(article["url"], "https://example.com/news/1")
        self.assertEqual(article["source"], "테스트")
        self.assertEqual(article["keyword"], "AI")
        self.assertEqual(article["content"], "기업 들이 AI 투자를 늘리고 있다.")

    def test_clean_text_removes_html(self):
        self.assertEqual(clean_text("&lt;b&gt;뉴스&lt;/b&gt; 내용"), "뉴스 내용")


if __name__ == "__main__":
    unittest.main()
