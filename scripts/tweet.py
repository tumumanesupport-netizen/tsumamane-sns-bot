"""
つむまね 自動ツイート投稿スクリプト
GitHub Actions から定期実行されます
"""
import os
import random
import tweepy
from datetime import datetime

# ── 認証 ────────────────────────────────────────────────────────────
client = tweepy.Client(
    consumer_key=os.environ["TWITTER_API_KEY"],
    consumer_secret=os.environ["TWITTER_API_SECRET"],
    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
    access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
)

# ── ツイートテンプレート ──────────────────────────────────────────────
TWEETS = [
    # アプリ紹介
    "📊 複数の証券口座をまとめて管理できる資産管理アプリ「つむまね」🎉\n\nSBI証券・楽天証券など14社に対応！\n口座をまたいで配当・積立を一括確認できます✨\n\n📱 App Store で「つむまね」を検索\n#資産管理 #投資 #配当",

    # 機能紹介①：配当シミュレーション
    "💰 20年後の配当収入はいくら？\n\n「つむまね」の配当シミュレーション機能で\n将来の不労所得を可視化できます📈\n\n複利の力で資産がどう育つか一目瞭然！\n\n📱 #つむまね で検索\n#配当投資 #FIRE #資産形成",

    # 機能紹介②：積立シミュレーション
    "📅 毎月の積立、ちゃんと管理できてますか？\n\n「つむまね」なら積立シミュレーションで\nNISA・iDeCoの将来資産を自動計算🔢\n\n目標額まであと何年かすぐわかる！\n\n📱 App Store「つむまね」\n#積立投資 #NISA #iDeCo",

    # 機能紹介③：複数口座
    "🏦 証券口座が複数あって管理が大変…\n\nそんな方に「つむまね」！\nSBI・楽天・松井・マネックスなど\n14社の口座を1つのアプリで管理🎯\n\n毎朝自動で残高を取得してくれます✨\n\n📱 #資産管理アプリ #投資管理",

    # お役立ち情報①
    "💡 投資の豆知識\n\n「複利」の力を知っていますか？\n年利5%で30年運用すると...\n\n100万円 → 約432万円に！📈\n\n「つむまね」で自分の資産がどう育つか\nシミュレーションしてみましょう🌱\n\n#複利 #長期投資 #資産形成",

    # お役立ち情報②
    "📊 ポートフォリオを定期的に見直していますか？\n\n「つむまね」なら証券口座の資産状況を\n自動集計してポートフォリオを可視化📉📈\n\n分散投資のバランスチェックに最適！\n\n📱 App Store「つむまね」\n#ポートフォリオ #分散投資",

    # 週次まとめ系
    "📅 今週の資産チェック、できてますか？\n\n「つむまね」なら証券口座の残高を\n毎朝自動で取得・集計！\n\n週1回アプリを開くだけで\n資産の推移が一目でわかります📊\n\n📱 #つむまね #資産管理 #投資",

    # ダウンロード促進
    "🎁 1ヶ月無料トライアル実施中！\n\n「つむまねプラス」で\n✅ 全証券口座の自動同期\n✅ 配当・積立シミュレーション\n✅ ポートフォリオ分析\n\nがすべて使えます📱\n\nApp Store「つむまね」で検索！\n#資産管理アプリ #投資アプリ",
]

def post_tweet():
    """ランダムにツイートを選んで投稿"""
    # 曜日でツイートを選ぶ（週7日に対応）
    day_of_week = datetime.now().weekday()  # 0=月, 6=日
    index = day_of_week % len(TWEETS)
    tweet_text = TWEETS[index]

    try:
        response = client.create_tweet(text=tweet_text)
        print(f"✅ ツイート成功: ID={response.data['id']}")
        print(f"内容: {tweet_text[:50]}...")
    except Exception as e:
        print(f"❌ エラー: {e}")
        raise

if __name__ == "__main__":
    post_tweet()
