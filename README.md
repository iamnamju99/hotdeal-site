# 핫딜픽 (hotdeal-site)

토스 쇼핑 실시간 특가와 쿠팡 핫딜을 한 화면에 모아 보여 주는 **1인 운영 핫딜 큐레이션 테스트 사이트**입니다.
정적 파일만으로 동작하며 GitHub Pages(또는 Cloudflare Pages)에 그대로 올릴 수 있습니다.

- 라이브: <https://iamnamju99.github.io/hotdeal-site/>

## 화면 구성

- 상단 필터: **전체 / 토스딜 / 쿠팡딜** 세그먼트 + **카테고리** 칩(식품·주방·생활·가전 …)
- 상품 카드: 상품 이미지, 플랫폼 배지(토스딜·쿠팡딜), 할인율, 상품명, 가격(정가 취소선), 갱신 시각, `rel="sponsored noopener"` 구매 링크
- 하단: 쿠팡 파트너스 · 토스 쇼핑 파트너스 **대가성(수수료) 고지** 및 가격 변동 안내
- 모바일 2열 / 태블릿·PC 자동 다열 반응형 (360px 이하 1열)

## 폴더 구조

```
hotdeal_site/
├─ index.html                 # 생성 결과물(직접 수정하지 말 것)
├─ data/
│  ├─ deals.json              # 토스+쿠팡 통합 데이터 (id, platform, title, price, image, affiliate_url, category, updated_at …)
│  └─ coupang_source.json     # 쿠팡 파트너스 링크/가격 수동 큐레이션 소스
├─ assets/                    # 상품 썸네일(로컬 상대경로 → 정적 호스팅에서 깨지지 않음)
├─ scripts/
│  └─ sync_from_toss.py       # 토스 수집기 갱신 → deals.json + index.html 재생성 파이프라인
├─ templates/
│  └─ index.html.template     # index.html 원본 템플릿
├─ sitemap.xml · robots.txt   # 검색엔진용 (스크립트가 자동 갱신)
└─ .nojekyll                  # GitHub Pages에서 Jekyll 처리 생략
```

## 갱신 방법

토스 쇼핑 TOP5 수집기(`toss_automation/toss_collector.py`)가 `toss_automation/hotdeals.json`을 새로 쓰면,
아래 한 줄로 사이트가 최신 상태가 됩니다.

```bash
python3 hotdeal_site/scripts/sync_from_toss.py
```

- `--no-download` : 쿠팡 썸네일을 새로 받지 않고 기존 `assets/` 재사용
- `--toss PATH` / `--coupang PATH` : 소스 경로 지정
- 하는 일: ① 썸네일 → `assets/` 복사·정규화(800×800 JPEG) ② `data/deals.json` 생성 ③ `index.html` 재생성 ④ `sitemap.xml`·`robots.txt` 갱신

쿠팡 상품을 추가·교체할 때는 `data/coupang_source.json`의 `items`에
`id, title, price, original_price, category, affiliate_url, image_url, image_file`을 넣고 스크립트를 다시 실행합니다.
(가격·이미지 URL은 쿠팡 상품 페이지에서 확인한 값)

## 배포

```bash
# GitHub Pages (main 브랜치 / 루트)
gh api -X POST repos/iamnamju99/hotdeal-site/pages \
  -f 'source[branch]=main' -f 'source[path]=/'
```

Cloudflare Pages를 쓸 경우 빌드 명령 없이 출력 디렉터리를 `hotdeal_site/`로 지정하면 됩니다.

## 고지

이 사이트는 쿠팡 파트너스 및 토스 쇼핑 파트너스 활동의 일환으로, 상품 링크를 통한 구매 시 일정액의 수수료를 제공받습니다.
상품 가격·재고·배송 조건은 실시간으로 변동될 수 있으며, 결제 시점의 최종 조건은 각 쇼핑몰에서 확인해 주세요.
