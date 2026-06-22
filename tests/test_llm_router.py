import unittest
from unittest.mock import patch

from scripts.llm_router import LLMError, LLMResult, call_with_fallback


class LLMRouterTest(unittest.TestCase):
    def test_falls_back_from_gemini_to_openrouter(self):
        config = {
            "fallback_order": ["gemini", "openrouter", "groq"],
            "providers": {
                "gemini": {"enabled": True, "model": "gemini-test"},
                "openrouter": {"enabled": True, "model": "openrouter-test"},
                "groq": {"enabled": True, "model": "groq-test"},
            },
            "generation": {"temperature": 0.2, "max_tokens": 700},
        }

        with patch("scripts.llm_router.call_gemini") as gemini, patch(
            "scripts.llm_router.call_openrouter"
        ) as openrouter, patch("scripts.llm_router.call_groq") as groq:
            gemini.side_effect = LLMError("gemini", "quota exhausted", status_code=429, quota_exhausted=True)
            openrouter.return_value = LLMResult(
                provider="openrouter",
                model="openrouter-test",
                content='{"summary":"ok","category":"기술","importance":3,"reason":"test"}',
                raw={},
            )

            result = call_with_fallback("prompt", config)

        self.assertEqual(result.provider, "openrouter")
        gemini.assert_called_once()
        openrouter.assert_called_once()
        groq.assert_not_called()


if __name__ == "__main__":
    unittest.main()
