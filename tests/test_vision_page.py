"""Check that status rendering can find each element it updates."""
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest


class PageElements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if 'id' in attributes:
            self.ids.append(attributes['id'])


class VisionPageTests(unittest.TestCase):
    def test_status_and_controls_have_matching_elements(self):
        path = Path(__file__).resolve().parents[1] / 'drone-gcs' / 'vision.html'
        html = path.read_text(encoding='utf-8')
        page = PageElements()
        page.feed(html)
        referenced = set(re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", html))
        self.assertTrue(referenced)
        self.assertEqual(referenced - set(page.ids), set(), 'JavaScript refers to missing elements')
        duplicates = [name for name, count in Counter(page.ids).items() if count > 1]
        self.assertEqual(duplicates, [])

