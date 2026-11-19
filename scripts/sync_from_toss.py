#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
핫딜 사이트 동기화 파이프라인
-----------------------------
토스 쇼핑 실시간 TOP5(`toss_automation/hotdeals.json`)와
쿠팡 파트너스 수동 큐레이션(`data/coupang_source.json`)을 합쳐

  1) 상품 썸네일을 `assets/` 로 복사(토스) / 다운로드(쿠팡)
  2) `data/deals.json` 생성
  3) `index.html` 재생성 (templates/index.html.template 기반)
  4) `sitemap.xml`, `robots.txt` 재생성

을 수행한다. 토스 수집기가 hotdeals.json을 갱신한 뒤 이 스크립트만 돌리면
사이트가 최신 상태가 된다.

사용법
    python3 scripts/sync_from_toss.py                # 전체 동기화
    python3 scripts/sync_from_toss.py --no-download  # 쿠팡 이미지는 받지 않고 기존 assets 재사용
    python3 scripts/sync_from_toss.py --toss /path/to/hotdeals.json

외부 의존성 없음(Pillow는 있으면 리사이즈, 없으면 원본 복사).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent.parent          # hotdeal_site/
REPO_ROOT = SITE_DIR.parent                                 # workspace root
KST = timezone(timedelta(hours=9))
SITE_URL = "https://iamnamju99.github.io/hotdeal-site/"
SITE_NAME = "핫딜픽"
SITE_DESC = "토스 쇼핑 실시간 특가와 쿠팡 오늘의 핫딜을 한 화면에 모았습니다."

PLATFORM_LABEL = {"toss": "토스딜", "coupang": "쿠팡딜"}

# 토스 상품명 → 카테고리 (키워드 우선순위대로 검사)
CATEGORY_RULES = [
    ("주방", ["김치통", "정리대", "주방", "냄비", "프라이팬", "밀폐"]),
    ("가전", ["청소기", "가습기", "온수매트", "선풍기", "에어컨", "건조기"]),
    ("생활", ["핫팩", "넥워머", "도어벨", "홈캠", "우편함", "수납", "화장품 정리"]),
    ("식품", ["만두", "계란", "구운란", "부대찌개", "참깨", "배추", "김치", "커피", "초콜릿"]),
]


def categorize(title: str, fallback: str = "기타") -> str:
    for category, keywords in CATEGORY_RULES:
        if any(k in title for k in keywords):
            return category
    return fallback


def won(value: int | None) -> str:
    return f"{value:,}원" if value else ""


def parse_price(text: str | None) -> int | None:
    """'11,400원' → 11400"""
    if not text:
        return None
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    return int(digits) if digits else None


def discount_rate(price: int | None, original: int | None) -> int | None:
    if not price or not original or original <= price:
        return None
    return round((original - price) / original * 100)


def optimize_image(src: Path, dest: Path, size: int = 800) -> None:
    """가능하면 Pillow로 정사각 리사이즈 + JPEG 저장(페이지 무게 절감)."""
    try:
        from PIL import Image  # type: ignore

        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size), Image.LANCZOS)
            canvas = Image.new("RGB", (size, size), (255, 255, 255))
            canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
            canvas.save(dest, "JPEG", quality=84, optimize=True)
    except Exception:  # Pillow 없음/디코딩 실패 → 원본 그대로
        shutil.copy2(src, dest)


def download(url: str, dest: Path, timeout: int = 25) -> bool:
    if dest.exists() and dest.stat().st_size > 1000:
        return True
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    tmp = dest.with_suffix(".part")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            tmp.write_bytes(resp.read())
        optimize_image(tmp, dest)
        tmp.unlink(missing_ok=True)
        return True
    except Exception as exc:  # 네트워크 차단 등
        print(f"  ! 썸네일 다운로드 실패 {url} ({exc})", file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return dest.exists()


def load_toss(toss_path: Path) -> tuple[list[dict], datetime | None]:
    if not toss_path.exists():
        print(f"  ! 토스 데이터 없음: {toss_path}", file=sys.stderr)
        return [], None
    raw = json.loads(toss_path.read_text(encoding="utf-8"))
    updated = datetime.fromtimestamp(toss_path.stat().st_mtime, KST)
    items = []
    for row in raw:
        if not row.get("title"):
            continue
        rank = row.get("rank")
        items.append(
            {
                "id": f"toss-{rank}-{row.get('share_link', '').rstrip('/').split('/')[-1]}",
                "platform": "toss",
                "title": row["title"],
                "price": parse_price(row.get("price")),
                "original_price": None,
                "image": None,
                "image_source": row.get("local_image"),
                "affiliate_url": row.get("share_link"),
                "category": categorize(row["title"]),
                "rank": rank,
                "updated_at": updated.isoformat(),
                "memo": (row.get("discount") or "").strip() or None,
            }
        )
    return items, updated


def load_coupang(source_path: Path) -> tuple[list[dict], datetime | None]:
    if not source_path.exists():
        print(f"  ! 쿠팡 소스 없음: {source_path}", file=sys.stderr)
        return [], None
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    updated = datetime.fromisoformat(payload.get("checked_at")) if payload.get("checked_at") else None
    items = []
    for row in payload.get("items", []):
        items.append(
            {
                "id": row["id"],
                "platform": "coupang",
                "title": row["title"],
                "price": row.get("price"),
                "original_price": row.get("original_price"),
                "image": None,
                "image_source": row.get("image_url"),
                "image_file": row.get("image_file"),
                "affiliate_url": row["affiliate_url"],
                "category": row.get("category") or categorize(row["title"]),
                "updated_at": (updated or datetime.now(KST)).isoformat(),
                "memo": row.get("memo"),
            }
        )
    return items, updated


def materialize_images(deals: list[dict], *, allow_download: bool) -> None:
    assets = SITE_DIR / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for deal in deals:
        if deal["platform"] == "toss":
            src = REPO_ROOT / "toss_automation" / (deal["image_source"] or "")
            if not src.exists():
                print(f"  ! 토스 이미지 없음: {src}", file=sys.stderr)
                continue
            name = f"toss-{deal['rank']}.jpg"
            optimize_image(src, assets / name)
            deal["image"] = f"assets/{name}"
        else:
            name = deal.get("image_file") or f"{deal['id']}.jpg"
            dest = assets / name
            if not dest.exists():
                if allow_download and deal["image_source"]:
                    download(deal["image_source"], dest)
                else:
                    print(f"  ! 쿠팡 이미지 없음(assets/{name})", file=sys.stderr)
            if dest.exists():
                deal["image"] = f"assets/{name}"


def build_card(deal: dict) -> str:
    title = html.escape(deal["title"])
    url = html.escape(deal["affiliate_url"], quote=True)
    platform = deal["platform"]
    badge = PLATFORM_LABEL[platform]
    rate = discount_rate(deal["price"], deal["original_price"])
    updated = datetime.fromisoformat(deal["updated_at"]).strftime("%m/%d %H:%M")

    image_html = (
        f'<img src="{html.escape(deal["image"])}" alt="{title}" width="800" height="800" loading="lazy" decoding="async">'
        if deal.get("image")
        else f'<div class="thumb-fallback" aria-hidden="true"><span>{html.escape(deal["category"])}</span></div>'
    )
    rate_html = f'<span class="rate-badge">{rate}%</span>' if rate else ""
    was_html = f'<span class="price-was">{won(deal["original_price"])}</span>' if rate else ""
    memo_html = f'<p class="card-memo">{html.escape(deal["memo"])}</p>' if deal.get("memo") else ""

    return f"""      <article class="card" data-platform="{platform}" data-category="{html.escape(deal['category'])}">
        <a class="card-media" href="{url}" target="_blank" rel="sponsored noopener">
          {image_html}
          <span class="platform-badge badge-{platform}">{badge}</span>
          {rate_html}
        </a>
        <div class="card-body">
          <span class="category-chip">{html.escape(deal['category'])}</span>
          <h3 class="card-title">{title}</h3>
          {memo_html}
          <p class="price"><span class="price-now">{won(deal['price'])}</span>{was_html}</p>
          <p class="card-meta">{updated} 갱신</p>
          <a class="cta" href="{url}" target="_blank" rel="sponsored noopener">
            최저가 확인
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false"><path d="M3 8h9M8.5 3.5 13 8l-4.5 4.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </a>
        </div>
      </article>"""


def render(deals: list[dict], updated_at: datetime) -> str:
    template = (SITE_DIR / "templates" / "index.html.template").read_text(encoding="utf-8")
    cards = "\n".join(build_card(d) for d in deals)

    categories = ["전체"] + sorted({d["category"] for d in deals})
    chips = "\n".join(
        f'          <button class="chip{" is-active" if c == "전체" else ""}" data-filter-category="{html.escape(c)}" '
        f'aria-pressed="{"true" if c == "전체" else "false"}">{html.escape(c)}</button>'
        for c in categories
    )
    toss_count = sum(1 for d in deals if d["platform"] == "toss")
    coupang_count = sum(1 for d in deals if d["platform"] == "coupang")
    upd_label = updated_at.strftime("%Y-%m-%d %H:%M")
    upd_short = updated_at.strftime("%m/%d %H:%M")

    jsonld = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": SITE_NAME,
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "item": {
                    "@type": "Product",
                    "name": d["title"],
                    "url": d["affiliate_url"],
                    "offers": {
                        "@type": "Offer",
                        "price": str(d["price"] or ""),
                        "priceCurrency": "KRW",
                        "availability": "https://schema.org/InStock",
                    },
                },
            }
            for i, d in enumerate(deals)
        ],
    }

    replacements = {
        "{{SITE_NAME}}": SITE_NAME,
        "{{SITE_DESC}}": SITE_DESC,
        "{{SITE_URL}}": SITE_URL,
        "{{UPDATED_AT_LABEL}}": upd_label,
        "{{UPDATED_AT_SHORT}}": upd_short,
        "{{UPDATED_AT_ISO}}": updated_at.isoformat(),
        "{{TOTAL}}": str(len(deals)),
        "{{TOSS_COUNT}}": str(toss_count),
        "{{COUPANG_COUNT}}": str(coupang_count),
        "{{CATEGORY_CHIPS}}": chips,
        "{{CARDS}}": cards,
        "{{JSONLD}}": json.dumps(jsonld, ensure_ascii=False, indent=2),
    }
    out = template
    for key, value in replacements.items():
        out = out.replace(key, value)
    return out


def write_sitemap(updated_at: datetime) -> None:
    lastmod = updated_at.strftime("%Y-%m-%d")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{SITE_URL}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>hourly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""
    (SITE_DIR / "sitemap.xml").write_text(xml, encoding="utf-8")

    robots = f"""User-agent: *
Allow: /
Disallow: /scripts/
Disallow: /templates/

Sitemap: {SITE_URL}sitemap.xml
"""
    (SITE_DIR / "robots.txt").write_text(robots, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="토스/쿠팡 핫딜 데이터를 사이트로 동기화")
    ap.add_argument("--toss", default=str(REPO_ROOT / "toss_automation" / "hotdeals.json"))
    ap.add_argument("--coupang", default=str(SITE_DIR / "data" / "coupang_source.json"))
    ap.add_argument("--no-download", action="store_true", help="쿠팡 썸네일을 새로 받지 않음")
    args = ap.parse_args()

    print(f"[1/4] 데이터 읽기 · 토스: {args.toss}")
    toss_items, toss_updated = load_toss(Path(args.toss))
    coupang_items, coupang_updated = load_coupang(Path(args.coupang))
    deals = toss_items + coupang_items
    if not deals:
        print("상품이 없습니다. 소스를 확인하세요.", file=sys.stderr)
        return 1

    print(f"[2/4] 썸네일 준비 · {len(deals)}개")
    materialize_images(deals, allow_download=not args.no_download)

    updated_at = max([t for t in (toss_updated, coupang_updated) if t] or [datetime.now(KST)])
    deals.sort(key=lambda d: (0 if d["platform"] == "toss" else 1, d.get("rank") or 0,
                              -(discount_rate(d["price"], d["original_price"]) or 0)))
    for d in deals:
        d.pop("image_source", None)
        d.pop("image_file", None)
        d.pop("rank", None)

    print("[3/4] data/deals.json 생성")
    payload = {
        "site": SITE_NAME,
        "site_url": SITE_URL,
        "updated_at": updated_at.isoformat(),
        "count": len(deals),
        "deals": deals,
    }
    (SITE_DIR / "data" / "deals.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("[4/4] index.html · sitemap.xml · robots.txt 생성")
    (SITE_DIR / "index.html").write_text(render(deals, updated_at), encoding="utf-8")
    write_sitemap(updated_at)

    print(f"완료: {len(deals)}개 상품 (토스 {len(toss_items)} · 쿠팡 {len(coupang_items)}), 기준 {updated_at:%Y-%m-%d %H:%M}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
