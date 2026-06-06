"""
夜20時投稿 - みんかぶ 買いコンセンサス 期待銘柄 TOP5
出所: https://minkabu.jp/financial_item_ranking/buy_picks_total
上昇余地（目標株価 vs 現在株価）でソートして上位5銘柄を投稿
"""
import os
import re
import tweepy
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

JST = pytz.timezone('Asia/Tokyo')

client = tweepy.Client(
    consumer_key=os.environ["TWITTER_API_KEY"],
    consumer_secret=os.environ["TWITTER_API_SECRET"],
    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
    access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
)

APP_URL = "https://apps.apple.com/jp/app/id6773302106"
CIRCLED = "①②③④⑤"
MAX_CHARS = 280
_URL_RE = re.compile(r'https?://\S+')

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


def tw_len(text: str) -> int:
    """Twitter加重文字数（日本語・絵文字=2文字、URL=23文字として計算）"""
    text = _URL_RE.sub('A' * 23, text)
    count = 0
    for ch in text:
        cp = ord(ch)
        if any([
            0x2E80 <= cp <= 0x303F,
            0x3040 <= cp <= 0x31BF,
            0x3200 <= cp <= 0x33FF,
            0x3400 <= cp <= 0x4DBF,
            0x4E00 <= cp <= 0x9FFF,
            0xF900 <= cp <= 0xFAFF,
            0xFE30 <= cp <= 0xFE6F,
            0xFF00 <= cp <= 0xFFEF,
        ]) or cp > 0xFFFF:
            count += 2
        else:
            count += 1
    return count


def parse_price(text: str):
    m = re.search(r"([\d,]+\.?\d*)", text.replace(",", ""))
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def get_minkabu_buy_ranking():
    """みんかぶ 買い予想総数ランキングをスクレイピング（上昇余地TOP5）"""
    stocks = []
    try:
        resp = requests.get(MINKABU_URL, headers=SCRAPE_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️ データ取得エラー: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("table tbody tr")

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        link = cells[1].find("a")
        if not link:
            continue
        href = link.get("href", "")
        code_m = re.search(r"/stock/(\d+)", href)
        if not code_m:
            continue
        code = code_m.group(1)
        link_text = link.get_text(separator="\n").strip()
        parts = link_text.split("\n")
        name = parts[-1].strip() if len(parts) >= 2 else parts[0].strip()
        current = parse_price(cells[3].get_text())
        if current is None or current <= 0:
            continue
        td4_text = cells[4].get_text(strip=True)
        if "買" not in td4_text:
            continue
        target = parse_price(td4_text)
        if target is None or target <= current:
            continue
        upside = (target - current) / current * 100
        stocks.append({"code": code, "name": name, "current": current,
                       "target": target, "upside": upside})

    if not stocks:
        return None
    stocks.sort(key=lambda x: x["upside"], reverse=True)
    return stocks[:5]


def build_tweet(top5: list, max_name: int = 99) -> str:
    today = datetime.now(JST).strftime("%-m/%-d")
    lines = [f"【{today} みんかぶ 期待銘柄 TOP5📊】"]
    lines.append("買いコンセンサス 上昇余地順")

    for i, s in enumerate(top5):
        name = s['name'][:max_name]
        lines.append(f"{CIRCLED[i]} {name} ▲{s['upside']:.1f}%")

    lines.append("")
    lines.append("📱つむまね（無料）")
    lines.append(APP_URL)
    lines.append("#日本株 #株式投資 #つむまね")
    return "\n".join(lines)


def format_tweet(top5: list) -> str:
    """280文字に収まるまで銘柄名を段階的に短縮"""
    for max_name in range(10, 2, -1):
        tweet = build_tweet(top5, max_name)
        if tw_len(tweet) <= MAX_CHARS:
            return tweet
    return build_tweet(top5, 3)


def main():
    print("📊 みんかぶ 期待銘柄データ取得中...")
    top5 = get_minkabu_buy_ranking()

    if not top5:
        print("❌ データ取得失敗 - スキップします")
        return

    tweet = format_tweet(top5)
    print(f"投稿内容({tw_len(tweet)}文字):\n{tweet}\n")

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
