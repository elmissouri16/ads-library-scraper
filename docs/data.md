# Data schema

Every ad is flattened to a single row with 39 fields. JSONL keeps lists and
nested values; CSV joins lists with `" | "` and JSON-encodes objects.

## Identity

| Field | Type | Notes |
| --- | --- | --- |
| `ad_archive_id` | str | Unique ad id; also used in the snapshot URL |
| `page_id` | str | Advertiser page id |
| `page_name` | str | Advertiser display name |
| `page_profile_uri` | str | Facebook page URL |
| `page_profile_picture_url` | str | Avatar CDN URL |
| `page_categories` | list[str] | Page categories when available |
| `page_like_count` | int | Followers/likes when available |

## Creative

| Field | Type | Notes |
| --- | --- | --- |
| `title` | str | First card/top-level title |
| `body` | str | Primary ad copy |
| `titles` | list[str] | Top-level + every card title |
| `bodies` | list[str] | Top-level + every card body |
| `cta_text` | str | e.g. `Shop now` |
| `cta_type` | str | Enum, e.g. `SHOP_NOW`, `LEARN_MORE` |
| `link_url` | str | Primary landing URL |
| `link_urls` | list[str] | All card URLs |
| `caption` | str | Display domain, e.g. `nike.com` |
| `link_description` | str | Meta description |
| `display_format` | str | `IMAGE`, `VIDEO`, `DCO`, `CAROUSEL`, … |
| `images` | list[str] | Original/resized image URLs |
| `videos` | list[str] | Video file URLs |
| `video_thumbnails` | list[str] | Poster frames for video ads |
| `cta_texts` | list[str] | All card CTAs |
| `byline` | str | Political/branded-content byline |
| `disclaimer_label` | str | Disclaimer shown on the ad |

`DCO` is Meta's dynamic creative optimisation: one ad shell with multiple
creative variations, so card lists can be long.

## Delivery

| Field | Type | Notes |
| --- | --- | --- |
| `is_active` | bool | Ad is currently running |
| `start_date` | str | UTC date `YYYY-MM-DD` |
| `end_date` | str | UTC date, or `null` when open-ended |
| `publisher_platforms` | list[str] | `FACEBOOK`, `INSTAGRAM`, `MESSENGER`, `AUDIENCE_NETWORK`, `THREADS` |
| `impressions_text` | str | Impression range when Meta exposes it |
| `spend` | obj | Spend range when exposed (usually political/EU only) |
| `currency` | str | Currency for `spend` |
| `reach_estimate` | obj | Reach estimate when exposed |
| `total_active_time` | int | Seconds active when exposed |
| `targeted_or_reached_countries` | list[str] | Usually empty on the logged-out view |

## Extras

| Field | Type | Notes |
| --- | --- | --- |
| `ad_snapshot_url` | str | `https://www.facebook.com/ads/archive/render_ad/?id=...` |
| `collation_count` | int | Variants in this collated group (`null` when not collated) |
| `collation_id` | str | Group id shared by variants |
| `contains_digital_created_media` | bool | AI-generated media flag |
| `gated_type` | str | e.g. `ELIGIBLE` |
| `ad_archive_id` | str | See identity |

## Example

```json
{
  "ad_archive_id": "1550534860016399",
  "page_id": "115939511520844",
  "page_name": "Perfect themes",
  "is_active": true,
  "start_date": "2026-05-19",
  "end_date": "2026-11-12",
  "display_format": "IMAGE",
  "cta_text": "Install now",
  "cta_type": "INSTALL_MOBILE_APP",
  "body": "Themepack is a FREE and personalized APP ...",
  "images": ["https://scontent..."],
  "publisher_platforms": ["FACEBOOK", "INSTAGRAM"],
  "ad_snapshot_url": "https://www.facebook.com/ads/archive/render_ad/?id=1550534860016399"
}
```

## Caveats

- `spend`, `currency`, `reach_estimate`, `total_active_time` and
  `targeted_or_reached_countries` are frequently empty for commercial
  advertisers outside political/EU transparency rules.
- `count` in the first page's `page_info` can be one higher than the number of
  unique `ad_archive_id`s if Meta revisits an entry during pagination; the
  client de-duplicates.
- Dates are converted from Meta's Unix timestamps to UTC dates. Cards in a
  carousel/DCO can have different creative but share ad-level dates.
