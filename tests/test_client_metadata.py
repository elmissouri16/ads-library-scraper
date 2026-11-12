import json
import unittest
from unittest.mock import patch

from ads_library import AdPage, AdsLibraryClient, SearchFilters
from ads_library.client import PageTokens


def _ad(ad_id: str, name: str = "Acme") -> dict:
    return {
        "node": {
            "collated_results": [
                {
                    "ad_archive_id": ad_id,
                    "is_active": True,
                    "start_date": 1700000000,
                    "snapshot": {
                        "page_id": "9",
                        "page_name": name,
                        "body": {"text": "copy"},
                    },
                }
            ]
        }
    }


CONNECTION = {
    "count": 42,
    "edges": [_ad("1")],
    "page_info": {"end_cursor": "cursor-1", "has_next_page": True},
}
NEXT_CONNECTION = {
    "edges": [_ad("2")],
    "page_info": {"end_cursor": None, "has_next_page": False},
}


def _html(connection: dict) -> str:
    return '<script>{"search_results_connection": ' + json.dumps(connection) + "}</script>"


def _client(connection: dict | None = None) -> tuple[AdsLibraryClient, SearchFilters]:
    client = AdsLibraryClient(request_delay=0)
    filters = SearchFilters(query="x")
    client._tokens = PageTokens(lsd="lsd", spin_r="1", spin_b="trunk", spin_t="1")
    client._filters = filters
    client._landing_html = _html(connection) if connection is not None else ""
    client._result_count = None
    return client, filters


class TestResultCount(unittest.TestCase):
    def test_count_is_none_before_search(self):
        client = AdsLibraryClient(request_delay=0)
        self.assertIsNone(client.result_count)
        client.close()

    def test_count_exposed_after_landing_page(self):
        client, filters = _client(CONNECTION)
        with patch.object(client, "_fetch_page", return_value=NEXT_CONNECTION):
            pages = list(client.iter_pages(filters))
        self.assertEqual(client.result_count, 42)
        self.assertEqual([len(p) for p in pages], [1, 1])

    def test_result_count_missing_is_none(self):
        connection = dict(CONNECTION)
        connection.pop("count")
        client, filters = _client(connection)
        with patch.object(client, "_fetch_page", return_value=NEXT_CONNECTION):
            list(client.iter_pages(filters))
        self.assertIsNone(client.result_count)

    def test_count_survives_pagination(self):
        client, filters = _client(CONNECTION)
        with patch.object(client, "_fetch_page", return_value=NEXT_CONNECTION):
            pages = list(client.iter_pages_detailed(filters))
        self.assertEqual([p.result_count for p in pages], [42, 42])


class TestPageMetadata(unittest.TestCase):
    def test_iter_pages_still_yields_plain_lists(self):
        client, filters = _client(CONNECTION)
        with patch.object(client, "_fetch_page", return_value=NEXT_CONNECTION):
            pages = list(client.iter_pages(filters))
        self.assertTrue(all(isinstance(page, list) for page in pages))
        self.assertTrue(all(isinstance(ad, dict) for page in pages for ad in page))

    def test_iter_pages_detailed_metadata(self):
        client, filters = _client(CONNECTION)
        with patch.object(client, "_fetch_page", return_value=NEXT_CONNECTION):
            pages = list(client.iter_pages_detailed(filters))
        self.assertTrue(all(isinstance(page, AdPage) for page in pages))
        self.assertEqual(pages[0].number, 1)
        self.assertEqual(pages[0].cursor, "cursor-1")
        self.assertTrue(pages[0].has_next_page)
        self.assertEqual(pages[1].number, 2)
        self.assertIsNone(pages[1].cursor)
        self.assertFalse(pages[1].has_next_page)
        self.assertEqual([ad["ad_archive_id"] for ad in pages[0].ads], ["1"])

    def test_search_unchanged(self):
        client, filters = _client(CONNECTION)
        # search() builds its own SearchFilters; reuse the warm session state.
        client._filters = SearchFilters(query="x")
        with patch.object(client, "_fetch_page", return_value=NEXT_CONNECTION):
            ads = client.search("x", limit=1)
        self.assertEqual(len(ads), 1)
        self.assertEqual(ads[0]["ad_archive_id"], "1")
        self.assertIn("ad_snapshot_url", ads[0])


if __name__ == "__main__":
    unittest.main()
