"""
週次まとめ投稿（土曜朝8時 JST）
- 週間出来高急増銘柄 TOP3（yfinance）
- 注目市場ニュース TOP2（Google News RSS）
"""
import os
import re
import tweepy
import yfinance as yf
import requests
from datetime import datetime
import pytz
import xml.etree.ElementTree as ET
from stocks_data import NIKKEI225

JST = pytz.timezone('Asia/Tokyo')
APP_URL = "https://apps.apple.com/jp/app/id6773302106"
MAX_CHARS = 280
CIRCLED = "①②③④⑤"
_URL_RE = re.compile(r'https?://\S+')

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

client = tweepy.Client(
    consumer_key=os.environ["TWITTER_API_KEY"],
    consumer_secret=os.environ["TWITTER_API_SECRET"],
    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
    access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
)


# ── Twitter文字数カウント ──────────────────────────────────────
def tw_len(text: str) -> int:
    """Twitter加重文字数（日本語・絵文字=2文字、URL=23文字）"""
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


# ── 出来高急増銘柄TOP3（yfinance） ───────────────────────────────
def get_volume_leaders(top_n: int = 3) -> list:
    """直近5日の出来高が前15日比で急増した銘柄＋週間騰落率を返す"""
    tickers = list(NIKKEI225.keys())
    try:
        raw = yf.download(
            tickers, period="25d", interval="1d",
            progress=False, auto_adjust=True
        )
        volume = raw["Volume"].dropna(how="all")
        close  = raw["Close"].dropna(how="all")

        if len(volume) < 10:
            return []

        # 直近5日 vs 前15日 の平均出来高比率
        recent_vol = volume.tail(5).mean()
        base_vol   = volume.iloc[-20:-5].mean()
        vol_ratio  = (recent_vol / base_vol).dropna().sort_values(ascending=False)

        # 週間騰落率（直近5日間）
        price_5d_ago = close.iloc[-6] if len(close) >= 6 else close.iloc[0]
        price_now    = close.iloc[-1]
        pct_change   = ((price_now - price_5d_ago) / price_5d_ago * 100).dropna()

        leaders = []
        for ticker in vol_ratio.index:
            name = NIKKEI225.get(ticker, ticker.replace(".T", ""))
            pct  = float(pct_change.get(ticker, 0))
            ratio = float(vol_ratio[ticker])
            if ratio < 1.1:          # 出来高増加が10%未満はスキップ
                continue
            leaders.append({
                "name":      name,
                "pct":       pct,
                "vol_ratio": ratio,   # 出来高倍率（参考）
            })
            if len(leaders) >= top_n:
                break

        return leaders

    except Exception as e:
        print(f"⚠️ 出来高データ取得エラー: {e}")
        return []


# ── 注目ニュース（Google News RSS） ─────────────────────────────
def get_market_news(limit: int = 2) -> list:
    """株式市場の注目ニュースをRSSから取得"""
    queries = [
        "日本株 注目銘柄 急騰 テーマ株",
        "日本株 IPO 新規上場 2026",
    ]
    news = []
    seen = set()

    for q in queries:
        url = (
            "https://news.google.com/rss/search"
            f"?q={q.replace(' ', '+')}&hl=ja&gl=JP&ceid=JP:ja"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as e:
            print(f"⚠️ ニュース取得エラー({q}): {e}")
            continue

        for item in root.findall('.//item'):
            title_elem = item.find('title')
            if title_elem is None or not title_elem.text:
                continue
            # 媒体名を除去
            title = title_elem.text.split(' - ')[0].strip()
            title = re.sub(r'[【】\[\]].*?[【】\[\]]', '', title).strip()
            title = title[:20] + '…' if len(title) > 20 else title
            if title and title not in seen:
                seen.add(title)
                news.append(title)
            if len(news) >= limit:
                break
        if len(news) >= limit:
            break

    return news[:limit]


# ── ツイート生成 ─────────────────────────────────────────────
def build_tweet(
    leaders: list,
    news:    list,
    max_name: int = 99,
) -> str:
    today_str = datetime.now(JST).strftime('%-m/%-d')
    lines = [f"📊 {today_str} 今週の注目情報"]

    # 出来高急増銘柄
    if leaders:
        lines.append("")
        lines.append("🔥 出来高急増TOP3")
        for i, s in enumerate(leaders):
            sign = "+" if s["pct"] >= 0 else ""
            name = s["name"][:max_name]
            lines.append(f"{CIRCLED[i]}{name} {sign}{s['pct']:.1f}%")

    # 注目ニュース
    if news:
        lines.append("")
        lines.append("📰 注目ニュース")
        for n in news:
            lines.append(n)

    lines.append("")
    lines.append("📱つむまね（無料）")
    lines.append(APP_URL)
    lines.append("#週間ランキング #出来高 #日本株 #つむまね")
    return "\n".join(lines)


def format_tweet(leaders, news) -> str:
    """280文字に収まるまで段階的に短縮"""
    for max_name in range(10, 2, -1):
        tweet = build_tweet(leaders, news, max_name)
        if tw_len(tweet) <= MAX_CHARS:
            return tweet
    return build_tweet(leaders, news, 3)


# ── メイン ────────────────────────────────────────────────
def main():
    print("📊 週次まとめデータ取得中...")

    leaders = get_volume_leaders()
    print(f"  出来高急増: {len(leaders)}件")
    for s in leaders:
        print(f"    - {s['name']} {s['pct']:+.1f}% (出来高{s['vol_ratio']:.1f}倍)")

    news = get_market_news()
    print(f"  ニュース: {len(news)}件")
    for n in news:
        print(f"    - {n}")

    if not leaders and not news:
        print("❌ データなし - スキップします")
        return

    tweet = format_tweet(leaders, news)
    print(f"\n投稿内容({tw_len(tweet)}文字):\n{tweet}\n")

    try:
        response = client.create_tweet(text=tweet)
        print(f"✅ 週次ツイート成功: ID={response.data['id']}")
    except tweepy.errors.Forbidden as e:
        print(f"❌ 403 Forbidden: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  本文: {e.response.text}")
        raise
    except Exception as e:
        print(f"❌ エラー: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()
