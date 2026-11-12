import json
import unittest

from ads_library.parsing import (
    connection_ads,
    extract_balanced_json,
    flatten_ad,
    parse_initial_results,
    parse_json_payload,
)


class TestJsonHelpers(unittest.TestCase):
    def test_extract_balanced_json_handles_nested_and_escapes(self):
        text = 'prefix {"a": {"b": "}"}, "c": "\\"{"} suffix'
        value = extract_balanced_json(text, 0)
        self.assertEqual(json.loads(value), {"a": {"b": "}"}, "c": '"{'})

    def test_parse_json_payload_reads_concatenated_objects(self):
        payload = '{"data": {"a": 1}}\n{"data": {"a": 2}}'
        self.assertEqual(parse_json_payload(payload)["data"], {"a": 1})

    def test_parse_initial_results_picks_largest_connection(self):
        html = (
            '<script>{"search_results_connection": {"edges": [], "page_info": {}}}</script>'
            '<script>{"search_results_connection": {"edges": [{"node": {}}],'
            ' "page_info": {"end_cursor": "abc", "has_next_page": true}}}</script>'
        )
        connection = parse_initial_results(html)
        self.assertEqual(len(connection["edges"]), 1)
        self.assertEqual(connection["page_info"]["end_cursor"], "abc")


class TestFlattenAd(unittest.TestCase):
    def test_flattens_cards_and_dates(self):
        item = {
            "ad_archive_id": 123,
            "is_active": True,
            "start_date": 1700000000,
            "end_date": 0,
            "publisher_platform": ["FACEBOOK"],
            "snapshot": {
                "page_id": "42",
                "page_name": "Acme",
                "cta_text": "Shop now",
                "link_url": "https://acme.test",
                "body": {"text": "Top level body"},
                "cards": [
                    {
                        "title": "Card title",
                        "body": "Card body",
                        "link_url": "https://acme.test/card",
                        "original_image_url": "https://cdn.test/a.jpg",
                        "video_preview_image_url": "https://cdn.test/a.jpg",
                    }
                ],
            },
        }
        ad = flatten_ad(item)
        self.assertEqual(ad["ad_archive_id"], "123")
        self.assertEqual(ad["start_date"], "2023-11-14")
        self.assertIsNone(ad["end_date"])
        self.assertEqual(ad["title"], "Card title")
        self.assertEqual(ad["body"], "Top level body")
        self.assertEqual(ad["titles"], ["Card title"])
        self.assertEqual(ad["bodies"], ["Top level body", "Card body"])
        self.assertEqual(ad["images"], ["https://cdn.test/a.jpg"])
        self.assertEqual(ad["ad_snapshot_url"], "https://www.facebook.com/ads/archive/render_ad/?id=123")

    def test_connection_ads_handles_collations(self):
        connection = {
            "edges": [
                {"node": {"collated_results": [{"ad_archive_id": "1"}, {"ad_archive_id": "2"}]}}
            ]
        }
        ads = connection_ads(connection)
        self.assertEqual([ad["ad_archive_id"] for ad in ads], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
