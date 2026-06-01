"""
夜20時投稿 - みんかぶ 買いコンセンサス 期待銘柄 TOP10
出所: https://minkabu.jp/financial_item_ranking/buy_picks_total
上昇余地（目標株価 vs 現在株価）でソートして上位10銘柄を投稿
"""
import os
import re
import tweepy
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

JST = pytz.timezone('Asia/Tokyo')

# ── Twitter認証 ───────────────────────────────────────────────────
client = tweepy.Client(
    consumer_key=os.environ["TWITTER_API_KEY"],
    consumer_secret=os.environ["TWITTER_API_SECRET"],
    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
    access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
)

PROMO = "\nSBI・楽天など14社を一括管理📱「つむまね」\n#日本株 #株式投資 #つむまね"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

MINKABU_URL = "https://minkabu.jp/financial_item_ranking/buy_picks_total"


def parse_price(text: str):
    """数字カンマ区切り文字列 → float。取得失敗時は None"""
    m = re.search(r"([\d,]+\.?\d*)", text.replace(",", ""))
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def get_minkabu_buy_ranking(pages: int = 2):
    """みんかぶ 買い予想総数ランキングをスクレイピング。
    Returns: list of dict {code, name, current, target, upside}
             upside% でソート済み、上位10件
    """
    stocks = []

    for page in range(1, pages + 1):
        url = MINKABU_URL if page == 1 else f"{MINKABU_URL}?page={page}"
        try:
            resp = requests.get(url, headers=SCRAPE_HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            print(f"⚠️ ページ{page}取得エラー: {e}")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("table tbody tr")

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            # 銘柄コード・名前: td[1] の <a href="/stock/XXXX">
            link = cells[1].find("a")
            if not link:
                continue
            href = link.get("href", "")
            code_m = re.search(r"/stock/(\d+)", href)
            if not code_m:
                continue
            code = code_m.group(1)

            # リンクテキスト "8411\nみずほFG" → 銘柄名は改行後
            link_text = link.get_text(separator="\n").strip()
            parts = link_text.split("\n")
            name = parts[-1].strip() if len(parts) >= 2 else parts[0].strip()

            # 現在株価: td[3]
            current = parse_price(cells[3].get_text())
            if current is None or current <= 0:
                continue

            # 目標株価 + 買いフラグ: td[4]
            td4_text = cells[4].get_text(strip=True)
            is_buy = "買" in td4_text
            if not is_buy:
                continue
            target = parse_price(td4_text)
            if target is None or target <= current:
                continue

            upside = (target - current) / current * 100
            stocks.append({
                "code": code,
                "name": name,
                "current": current,
                "target": target,
                "upside": upside,
            })

    if not stocks:
        return None

    # 上昇余地が大きい順にソートして上位10件
    stocks.sort(key=lambda x: x["upside"], reverse=True)
    return stocks[:10]


def format_tweet(top10: list) -> str:
    today = datetime.now(JST).strftime("%-m/%-d")
    lines = [f"【{today} みんかぶ 期待銘柄 TOP10】", "買いコンセンサス 上昇余地順📊", ""]

    for i, s in enumerate(top10):
        lines.append(f"{CIRCLED[i]} {s['name']}　▲{s['upside']:.1f}%")

    lines.append(PROMO)
    return "\n".join(lines)


def main():
    print("📊 みんかぶ 期待銘柄データ取得中...")
    top10 = get_minkabu_buy_ranking(pages=2)

    if not top10:
        print("❌ データ取得失敗 - スキップします")
        return

    tweet = format_tweet(top10)
    print(f"投稿内容({len(tweet)}文字):\n{tweet}\n")

    try:
        response = client.create_tweet(text=tweet)
        print(f"✅ 夜ツイート成功: ID={response.data['id']}")
    except tweepy.errors.Forbidden as e:
        print("❌ 403 Forbidden")
        if hasattr(e, "response") and e.response is not None:
            print(f"  response: {e.response.text}")
        raise
    except Exception as e:
        print(f"❌ 投稿エラー: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()
