"""
朝8時投稿 - 前日の日本株 急騰・急落TOP5
急騰銘柄には100株あたりの購入目安金額を掲載
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

PROMO = "\nSBI・楽天など14社を一括管理📱「つむまね」\n#日本株 #株式投資 #つむまね"
CIRCLED = "①②③④⑤"


def fmt_100share(price: float) -> str:
    """100株あたりの金額を万円単位でフォーマット（例: 59万円）"""
    total = int(price * 100)
    if total >= 10000:
        return f"{total // 10000}万円"
    return f"{total:,}円"


def get_movers():
    """前日の急騰・急落銘柄を取得。(top5, bot5, last_prices) を返す"""
    tickers = list(NIKKEI225.keys())
    try:
        raw = yf.download(tickers, period="5d", interval="1d",
                          progress=False, auto_adjust=True)
        prices = raw["Close"]
        prices = prices.dropna(how="all").tail(2)
        if len(prices) < 2:
            return None, None, None

        prev, last = prices.iloc[-2], prices.iloc[-1]
        pct = ((last - prev) / prev * 100).dropna().sort_values(ascending=False)

        top5 = pct.head(5)
        bot5 = pct.tail(5)
        return top5, bot5, last   # last = 直近終値 Series
    except Exception as e:
        print(f"データ取得エラー: {e}")
        return None, None, None


def format_tweet(top5, bot5, last) -> str:
    today = datetime.now(JST).strftime('%-m/%-d')

    # ── 急騰TOP5（100株価格付き） ────────────────────────────────
    rise_lines = []
    for i, (ticker, pct) in enumerate(top5.items()):
        name = NIKKEI225.get(ticker, ticker.replace(".T", ""))
        price = last.get(ticker, None)
        if price is not None and not pd.isna(price):
            price_tag = f"〔100株:{fmt_100share(price)}〕"
        else:
            price_tag = ""
        rise_lines.append(f"{CIRCLED[i]} {name}　▲{pct:.1f}%{price_tag}")

    # ── 急落TOP5（価格なし） ─────────────────────────────────────
    fall_lines = []
    for i, (ticker, pct) in enumerate(bot5.items()):
        name = NIKKEI225.get(ticker, ticker.replace(".T", ""))
        fall_lines.append(f"{CIRCLED[i]} {name}　▼{abs(pct):.1f}%")

    def build(with_price: bool) -> str:
        lines = [f"【{today} 東証 急騰・急落 TOP5】", ""]
        lines.append("🚀 急騰")
        lines += rise_lines if with_price else [
            f"{CIRCLED[i]} {NIKKEI225.get(t, t.replace('.T',''))}　▲{p:.1f}%"
            for i, (t, p) in enumerate(top5.items())
        ]
        lines.append("")
        lines.append("📉 急落")
        lines += fall_lines
        lines.append(PROMO)
        return "\n".join(lines)

    tweet = build(with_price=True)

    # 280文字を超えた場合は100株価格を省略してフォールバック
    if len(tweet) > 280:
        print(f"⚠️ {len(tweet)}文字 > 280文字のため100株価格を省略します")
        tweet = build(with_price=False)

    return tweet


def main():
    print("📊 急騰・急落データ取得中...")
    top5, bot5, last = get_movers()

    if top5 is None or bot5 is None:
        print("❌ データ取得失敗 - スキップします")
        return

    tweet = format_tweet(top5, bot5, last)
    print(f"投稿内容({len(tweet)}文字):\n{tweet}\n")

    try:
        response = client.create_tweet(text=tweet)
        print(f"✅ 朝ツイート成功: ID={response.data['id']}")
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
