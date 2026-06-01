"""
昼12時投稿 - 海外主要株 前日急騰・急落TOP5（国名付き）
対象: 米国市場上場の主要株 + 欧州・アジア ADR
"""
import os
import tweepy
import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
from stocks_data import OVERSEAS_STOCKS

JST = pytz.timezone('Asia/Tokyo')

# ── Twitter認証 ───────────────────────────────────────────────────
client = tweepy.Client(
    consumer_key=os.environ["TWITTER_API_KEY"],
    consumer_secret=os.environ["TWITTER_API_SECRET"],
    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
    access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
)

PROMO = "\nSBI・楽天など14社を一括管理📱「つむまね」\n#米国株 #海外投資 #つむまね"
CIRCLED = "①②③④⑤"


def get_overseas_movers():
    """直近の海外株急騰・急落銘柄を取得"""
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

        top5 = pct.head(5)
        bot5 = pct.tail(5)
        return top5, bot5
    except Exception as e:
        print(f"データ取得エラー: {e}")
        return None, None


def format_tweet(top5, bot5) -> str:
    today = datetime.now(JST).strftime('%-m/%-d')
    lines = [f"【{today} 海外株 急騰・急落 TOP5】", ""]

    lines.append("🚀 急騰")
    for i, (ticker, pct) in enumerate(top5.items()):
        name, country = OVERSEAS_STOCKS.get(ticker, (ticker, "?"))
        lines.append(f"{CIRCLED[i]} {name}　▲{pct:.1f}%〔{country}〕")

    lines.append("")
    lines.append("📉 急落")
    for i, (ticker, pct) in enumerate(bot5.items()):
        name, country = OVERSEAS_STOCKS.get(ticker, (ticker, "?"))
        lines.append(f"{CIRCLED[i]} {name}　▼{abs(pct):.1f}%〔{country}〕")

    lines.append(PROMO)
    return "\n".join(lines)


def main():
    print("🌍 海外株データ取得中...")
    top5, bot5 = get_overseas_movers()

    if top5 is None or bot5 is None:
        print("❌ データ取得失敗 - スキップします")
        return

    tweet = format_tweet(top5, bot5)
    print(f"投稿内容({len(tweet)}文字):\n{tweet}\n")

    try:
        response = client.create_tweet(text=tweet)
        print(f"✅ 海外株ツイート成功: ID={response.data['id']}")
    except tweepy.errors.Forbidden as e:
        print(f"❌ 403 Forbidden")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  response: {e.response.text}")
        raise
    except Exception as e:
        print(f"❌ 投稿エラー: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()
