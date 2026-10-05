import unittest

from backend.ingest.parser import message_body_and_parse_text


class PipelineMailBodyTests(unittest.TestCase):
    def test_notes_body_is_separate_from_preview_fallback(self):
        body, parse_text = message_body_and_parse_text({
            "body": {"content": "<html><head><meta charset='utf-8'></head><body>完整邮件正文<br>第二行</body></html>"},
            "bodyPreview": "被截断的预览",
        })

        self.assertEqual(body, "完整邮件正文\n第二行")
        self.assertEqual(parse_text, "完整邮件正文\n第二行")

    def test_preview_is_parser_fallback_but_not_notes_body(self):
        body, parse_text = message_body_and_parse_text({
            "body": {"content": ""},
            "bodyPreview": "邮件预览",
        })

        self.assertEqual(body, "")
        self.assertEqual(parse_text, "邮件预览")


if __name__ == "__main__":
    unittest.main()
