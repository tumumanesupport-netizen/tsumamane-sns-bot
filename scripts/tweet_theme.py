"""
⑥ テーマ株投稿 - 平日 15:30 JST（市場引け後）
当日一番動いたテーマの銘柄 TOP3 を投稿
テーマ: 半導体 / AI・DX / 防衛関連 / インバウンド / 高配当
"""
import os
import re
import tweepy
import yfinance as yf
from datetime import datetime
import pytz
from theme_stocks import THEME_STOCKS, THEME_HASHTAGS

JST = pytz.timezone('Asia/Tokyo')
APP_URL = "https://apps.apple.com/jp/app/id6773302106"
MAX_CHARS = 280
CIRCLED = "①②③④⑤"
_URL_RE = re.compile(r'https?://\S+')

client = tweepy.Client(
    consumer_key=os.environ["TWITTER_API_KEY"],
    consumer_secret=os.environ["TWITTER_API_SECRET"],
    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
    access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
)


# ── Twitter文字数カウント ─────────────────────────────────────
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


# ── テーマ別パフォーマンス取得 ────────────────────────────────
def get_theme_movers() -> dict | None:
    """各テーマの当日パフォーマンスを一括取得"""
    all_tickers = list({t for stocks in THEME_STOCKS.values() for t in stocks})
    try:
        raw = yf.download(all_tickers, period="5d", interval="1d",
                          progress=False, auto_adjust=True)
        prices = raw["Close"].dropna(how="all").tail(2)
        if len(prices) < 2:
            return None
        prev, last = prices.iloc[-2], prices.iloc[-1]
        pct_all = ((last - prev) / prev * 100).dropna()
    except Exception as e:
        print(f"⚠️ データ取得エラー: {e}")
        return None

    result = {}
    for theme, stocks in THEME_STOCKS.items():
        movers = []
        for ticker, name in stocks.items():
            if ticker in pct_all.index:
                pct = float(pct_all[ticker])
                movers.append({"name": name, "pct": pct})
        if not movers:
            continue
        avg = sum(m["pct"] for m in movers) / len(movers)
        # 動きの大きい銘柄順にソート
        movers.sort(key=lambda x: abs(x["pct"]), reverse=True)
        result[theme] = {"avg": avg, "movers": movers[:3]}

    return result if result else None


def pick_hottest_theme(themes: dict) -> tuple:
    """上昇率が高いテーマを優先、なければ絶対値最大テーマ"""
    rising = {t: d for t, d in themes.items() if d["avg"] >= 0.5}
    if rising:
        best = max(rising, key=lambda t: rising[t]["avg"])
        return best, rising[best]
    best = max(themes, key=lambda t: abs(themes[t]["avg"]))
    return best, themes[best]


# ── ツイート生成 ─────────────────────────────────────────────
def build_tweet(theme: str, data: dict, max_name: int = 99) -> str:
    today = datetime.now(JST).strftime('%-m/%-d')
    avg = data["avg"]
    sign = "+" if avg >= 0 else ""
    hashtags = THEME_HASHTAGS.get(theme, "#日本株")

    lines = [f"【{today} テーマ株 注目📊】"]
    lines.append("")
    lines.append(f"🔥 {theme} {sign}{avg:.1f}%")
    for i, m in enumerate(data["movers"]):
        name = m["name"][:max_name]
        msign = "+" if m["pct"] >= 0 else ""
        lines.append(f"{CIRCLED[i]}{name} {msign}{m['pct']:.1f}%")
    lines.append("")
    lines.append("📱つむまね（無料）")
    lines.append(APP_URL)
    lines.append(f"{hashtags} #日本株 #つむまね")
    return "\n".join(lines)


def format_tweet(theme: str, data: dict) -> str:
    """280文字に収まるまで銘柄名を段階的に短縮"""
    for max_name in range(12, 2, -1):
        tweet = build_tweet(theme, data, max_name)
        if tw_len(tweet) <= MAX_CHARS:
            return tweet
    return build_tweet(theme, data, 3)


# ── メイン ────────────────────────────────────────────────
def main():
    print("📊 テーマ株データ取得中...")
    themes = get_theme_movers()

    if not themes:
        print("❌ データ取得失敗 - スキップします")
        return

    theme, data = pick_hottest_theme(themes)
    print(f"  選択テーマ: {theme} (平均{data['avg']:+.1f}%)")
    for m in data["movers"]:
        print(f"    - {m['name']} {m['pct']:+.1f}%")

    tweet = format_tweet(theme, data)
    print(f"\n投稿内容({tw_len(tweet)}文字):\n{tweet}\n")

    try:
        response = client.create_tweet(text=tweet)
        print(f"✅ テーマ株ツイート成功: ID={response.data['id']}")
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
