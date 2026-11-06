"""Minimal renderer contract tests (stdlib only)."""
import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RenderTests(unittest.TestCase):
    def test_article_image_caption_and_title(self):
        renderer = load("render_article")
        source = (ROOT / "examples/article.example.md").read_text(encoding="utf-8")
        title, body = renderer.render(source, "2026.11.06", "Agent实验室", "AI热点")
        self.assertEqual(body.count("<img"), len(re.findall(r"图\d+｜", body)))
        self.assertEqual(body.count("<img"), 1)
        self.assertNotIn(title, body)
        self.assertNotIn("`", body)
        self.assertNotIn(str(Path.home()), body)

    def test_daily_uses_same_renderer(self):
        daily = load("daily_layout")
        data = __import__("json").loads((ROOT / "examples/daily.example.json").read_text(encoding="utf-8"))
        html = daily.render(data)
        self.assertEqual(html.count("<h2"), len(data["items"]) + 1)  # items + 今日观察
        self.assertIn("每天60秒看懂AI时间", daily.article_title(data, data["items"]))
        self.assertNotIn("example.com", html)

    def test_daily_rejects_placeholder_source(self):
        daily = load("daily_layout")
        data = __import__("json").loads((ROOT / "examples/daily.example.json").read_text(encoding="utf-8"))
        data["items"][0]["url"] = "https://example.com/fake"
        with self.assertRaises(ValueError):
            daily.validate(data)


if __name__ == "__main__":
    unittest.main()
