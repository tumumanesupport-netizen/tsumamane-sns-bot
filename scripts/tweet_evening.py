"""
夜20時投稿 - 今後期待される銘柄TOP10（1ヶ月モメンタム）
"""
import os
import tweepy
import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
from stocks_data import NIKKEI225

JST = pytz.timezone('Asia/Tokyo')

# ── Twitter認証 ───────────────────────────────────────────────────
client = tweepy.Client(
    consumer_key=os.environ["TWITTER_API_KEY"],
    consumer_secret=os.environ["TWITTER_API_SECRET"],
    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
    access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
)

PROMO = "\n📱SBI・楽天など14社の証券口座を一括管理\n#つむまね #日本株 #資産管理"

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


def get_top_momentum():
    """1ヶ月モメンタムでTOP10を算出"""
    tickers = list(NIKKEI225.keys())
    try:
        raw = yf.download(tickers, period="35d", interval="1d",
                          progress=False, auto_adjust=True)
        prices = raw["Close"].dropna(how="all")

        if len(prices) < 20:
            return None

        # 1ヶ月（約20営業日）騰落率
        first = prices.iloc[0]
        last = prices.iloc[-1]
        pct = ((last - first) / first * 100).dropna()

        # 25日移動平均を上回っている銘柄だけに絞る（トレンド確認）
        ma25 = prices.tail(25).mean()
        above_ma = pct[last > ma25]

        top10 = above_ma.sort_values(ascending=False).head(10)
        return top10
    except Exception as e:
        print(f"データ取得エラー: {e}")
        return None


def format_tweet(top10):
    today = datetime.now(JST).strftime('%-m/%-d')
    lines = [f"🌟 {today} 注目・期待銘柄TOP10\n（1ヶ月モメンタム）\n"]

    for i, (ticker, pct) in enumerate(top10.items()):
        name = NIKKEI225.get(ticker, ticker.replace(".T", ""))
        lines.append(f"{CIRCLED[i]}{name}({pct:+.1f}%)")

    lines.append(PROMO)
    return "\n".join(lines)


def main():
    print("🌟 期待銘柄データ取得中...")
    top10 = get_top_momentum()

    if top10 is None or len(top10) < 5:
        print("❌ データ取得失敗 - スキップします")
        return

    tweet = format_tweet(top10)
    print(f"投稿内容({len(tweet)}文字):\n{tweet}\n")

    try:
        response = client.create_tweet(text=tweet)
        print(f"✅ 夜ツイート成功: ID={response.data['id']}")
    except Exception as e:
        print(f"❌ 投稿エラー: {e}")
        raise


if __name__ == "__main__":
    main()
