"""
朝8時投稿 - 前日の日本株 急騰・急落TOP5
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

PROMO = "\n📱複数の証券口座を自動集計！\n#つむまね #日本株 #投資"

CIRCLED = "①②③④⑤"

def get_movers():
    """前日の急騰・急落銘柄を取得"""
    tickers = list(NIKKEI225.keys())
    try:
        # 直近5営業日のデータを取得（週末・祝日対応）
        raw = yf.download(tickers, period="5d", interval="1d",
                          progress=False, auto_adjust=True)
        prices = raw["Close"]

        # 直近2日の終値で騰落率を計算
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


def format_tweet(top5, bot5):
    today = datetime.now(JST).strftime('%-m/%-d')
    lines = [f"📊 {today} 東証 前日急騰・急落\n"]

    lines.append("🚀 急騰TOP5")
    for i, (ticker, pct) in enumerate(top5.items()):
        name = NIKKEI225.get(ticker, ticker.replace(".T", ""))
        lines.append(f"{CIRCLED[i]}{name} +{pct:.1f}%")

    lines.append("\n📉 急落TOP5")
    for i, (ticker, pct) in enumerate(bot5.items()):
        name = NIKKEI225.get(ticker, ticker.replace(".T", ""))
        lines.append(f"{CIRCLED[i]}{name} {pct:.1f}%")

    lines.append(PROMO)
    return "\n".join(lines)


def main():
    print("📊 急騰・急落データ取得中...")
    top5, bot5 = get_movers()

    if top5 is None or bot5 is None:
        print("❌ データ取得失敗 - スキップします")
        return

    tweet = format_tweet(top5, bot5)
    print(f"投稿内容({len(tweet)}文字):\n{tweet}\n")

    try:
        response = client.create_tweet(text=tweet)
        print(f"✅ 朝ツイート成功: ID={response.data['id']}")
    except tweepy.errors.Forbidden as e:
        print(f"❌ 403 Forbidden エラー")
        print(f"  メッセージ: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"  レスポンス本文: {e.response.text}")
            print(f"  ステータスコード: {e.response.status_code}")
        if hasattr(e, 'api_codes'):
            print(f"  APIエラーコード: {e.api_codes}")
        if hasattr(e, 'api_errors'):
            print(f"  APIエラー詳細: {e.api_errors}")
        raise
    except Exception as e:
        print(f"❌ 投稿エラー: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()
