"""
リリース記念 告知ツイート（1回のみ実行）
"""
import os
import tweepy

client = tweepy.Client(
    consumer_key=os.environ["TWITTER_API_KEY"],
    consumer_secret=os.environ["TWITTER_API_SECRET"],
    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
    access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
)

TWEET = """🎉 つむまね、本日リリースしました！

複数の証券口座をまとめて管理できる資産管理アプリです📊

✅ SBI・楽天など14社の口座を一括管理
✅ 配当シミュレーションで将来の不労所得を可視化
✅ 積立シミュレーションでNISA・iDeCoを最適化
✅ 毎朝、残高を自動取得

資産を紡ぐ、未来を描く——

📱 App Store で無料ダウンロード
https://apps.apple.com/jp/app/id6773302106

#つむまね #資産管理 #投資 #NISA #配当投資 #新着アプリ"""

def main():
    print(f"投稿内容({len(TWEET)}文字):\n{TWEET}\n")
    try:
        response = client.create_tweet(text=TWEET)
        print(f"✅ リリース告知ツイート成功: ID={response.data['id']}")
    except Exception as e:
        print(f"❌ エラー: {e}")
        raise

if __name__ == "__main__":
    main()
