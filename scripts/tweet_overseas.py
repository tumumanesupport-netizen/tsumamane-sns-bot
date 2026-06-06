"""
昼12時投稿 - 海外主要株 前日急騰・急落 TOP3（国名付き）
対象: 米国市場上場の主要株 + 欧州・アジア ADR
"""
import os
import re
import tweepy
import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
from stocks_data import OVERSEAS_STOCKS

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


def get_overseas_movers():
    """直近の海外株急騰・急落銘柄 TOP3 を取得"""
    tickers = list(OVERSEAS_STOCKS.keys())
    try:
        raw = yf.download(tickers, period="5d", interval="1d",
                          progress=False, auto_adjust=True)
        prices = raw["Close"]
        prices = prices.dropna(how="all").tail(2)
        if len(prices) < 2:
            return None, None
        prev, last = prices.iloc[-2], prices.iloc[-1]
        pct = ((last - prev) / prev * 100).dropna().sort_values(ascending=False)
        return pct.head(3), pct.tail(3)
    except Exception as e:
        print(f"データ取得エラー: {e}")
        return None, None


def build_tweet(top, bot, max_name: int = 99) -> str:
    today = datetime.now(JST).strftime('%-m/%-d')
    lines = [f"【{today} 海外株 急騰・急落 TOP3】"]

    lines.append("🚀 急騰")
    for i, (ticker, pct) in enumerate(top.items()):
        name, country = OVERSEAS_STOCKS.get(ticker, (ticker, "?"))
        name = name[:max_name]
        lines.append(f"{CIRCLED[i]} {name} +{pct:.1f}%[{country}]")

    lines.append("📉 急落")
    for i, (ticker, pct) in enumerate(bot.items()):
        name, country = OVERSEAS_STOCKS.get(ticker, (ticker, "?"))
        name = name[:max_name]
        lines.append(f"{CIRCLED[i]} {name} -{abs(pct):.1f}%[{country}]")

    lines.append("")
    lines.append("📱つむまね（無料）")
    lines.append(APP_URL)
    lines.append("#米国株 #海外投資 #つむまね")
    return "\n".join(lines)


def format_tweet(top, bot) -> str:
    """280文字に収まるまで銘柄名を段階的に短縮"""
    for max_name in range(12, 2, -1):
        tweet = build_tweet(top, bot, max_name)
        if tw_len(tweet) <= MAX_CHARS:
            return tweet
    return build_tweet(top, bot, 3)


def main():
    print("🌍 海外株データ取得中...")
    top, bot = get_overseas_movers()

    if top is None or bot is None:
        print("❌ データ取得失敗 - スキップします")
        return

    tweet = format_tweet(top, bot)
    print(f"投稿内容({tw_len(tweet)}文字):\n{tweet}\n")

    try:
        response = client.create_tweet(text=tweet)
        print(f"✅ 海外株ツイート成功: ID={response.data['id']}")
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
