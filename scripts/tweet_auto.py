"""
AI自動生成投稿 - 30分ごと（48本/日）
時間帯ごとにテーマを変え、「公式配信」と「個人コメント」を交互に投稿

時間帯別テーマ:
  5〜 7時: 朝活・今日の展望
  8〜11時: 市場オープン・急騰急落
 12〜14時: 前場振り返り・後場注目
 15〜17時: 引け後分析・本日まとめ
 18〜23時: 長期投資・NISA・iDeCo教育
  0〜 4時: 米国株・翌日展望

投稿スタイル（分で交互）:
  :00 → 公式配信スタイル（データ・断言系）
  :30 → 個人コメントスタイル（体験・共感系）

つむまね機能アピール（ローテーション）:
  複数証券口座の管理 / 資産管理 / 資産シミュレーション など

PHASE 2（X Basic plan取得後）:
  get_viral_x_posts() のコメントアウトを外してバズ投稿分析を有効化
"""
import os
import re
import sys
import tweepy
import requests
import anthropic
import xml.etree.ElementTree as ET
from datetime import datetime
import pytz

JST = pytz.timezone('Asia/Tokyo')
APP_URL = "https://apps.apple.com/jp/app/id6773302106"
MAX_CHARS = 280
_URL_RE = re.compile(r'https?://\S+')

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

# ── 時間帯別テーマ設定 ───────────────────────────────────────
HOUR_THEMES = [
    # (開始時, 終了時, ラベル, フォーカス, 推奨フォーマット)
    (5,  8,  "朝活タイム",
     "今日の市場展望・前日の米国株動向・朝イチで確認すべきこと",
     "「今日の注目ポイント」「朝に確認すべき3つのこと」など朝活投資家向け"),
    (8,  12, "市場オープン",
     "急騰急落銘柄・テーマ株・今日動きそうな銘柄・出来高",
     "「今日の注目銘柄」「急騰中の○○」など速報・ランキング形式"),
    (12, 15, "お昼の相場",
     "前場の振り返り・後場の注目点・今日のテーマ株・セクター動向",
     "「前場まとめ」「後場はこれに注目」など中間レポート形式"),
    (15, 18, "引け後分析",
     "本日の相場まとめ・値動きの理由・明日への視点・注目銘柄",
     "「今日の相場を振り返る」「明日注目すべき理由」など分析・考察形式"),
    (18, 24, "夜の学習タイム",
     "NISA・iDeCo・長期投資・高配当・資産運用の基礎知識・初心者向け解説",
     "「知らないと損」「○○円から始める」など教育・啓発形式"),
    (0,  5,  "深夜・米国市場",
     "米国株・ドル円・ナスダック・S&P500・翌日の日本市場への影響",
     "「米国株速報」「円安・円高の影響」など海外市場連動形式"),
]


def get_hour_theme(hour: int) -> dict:
    """現在時刻に対応するテーマを返す"""
    for start, end, label, focus, fmt in HOUR_THEMES:
        if start <= hour < end:
            return {"label": label, "focus": focus, "format": fmt}
    return {"label": "投資情報", "focus": "株式投資・NISA・資産運用", "format": "自由形式"}


# ── 投稿スタイル設定（:00=公式 / :30=個人コメント 交互） ─────────
POST_STYLES = {
    "official": {
        "label": "公式配信スタイル",
        "instruction": (
            "権威ある情報発信者として書く。\n"
            "・「〜が重要です」「〜を確認しましょう」「〜のポイントをまとめました」など断言・まとめ系\n"
            "・数字・データ・事実を中心に構成し、信頼感を出す\n"
            "・絵文字は📊📈📉💹🔔など情報系を使う\n"
            "・テンポよく箇条書きや番号リストを活用する"
        ),
    },
    "personal": {
        "label": "個人コメントスタイル",
        "instruction": (
            "一般の個人投資家が気軽に呟くような口調で書く。\n"
            "・「〜してみた」「〜だよね」「〜って知ってた？」「正直〜」など体験・共感系\n"
            "・失敗談・気づき・驚きを含めると親近感が増す\n"
            "・絵文字は😅🤔💡🙌😮✨など感情系を使う\n"
            "・アプリは「使ってみたら便利だった」的な自然な口コミ推薦にする"
        ),
    },
}


def get_post_style(minute: int) -> dict:
    """分が0なら公式、30なら個人コメントスタイルを返す"""
    return POST_STYLES["personal"] if minute >= 30 else POST_STYLES["official"]


# ── つむまねの機能アピール（ローテーション） ─────────────────────
APP_FEATURES = [
    "複数の証券口座（SBI・楽天・マネックス・松井など）をまとめて管理できるのが「つむまね」",
    "全口座の資産を一画面で把握できる資産管理アプリが「つむまね」",
    "老後の資産を将来シミュレーションできるのが「つむまね」",
    "NISA・iDeCo口座の残高もひとまとめに確認できるのが「つむまね」",
    "配当金・分配金の受取履歴を口座横断で自動管理できるのが「つむまね」",
    "保有株のポートフォリオをグラフで可視化できるのが「つむまね」",
    "各口座の損益をリアルタイムで比較・確認できるのが「つむまね」",
    "投資初心者でも直感的に使いやすい資産管理アプリが「つむまね」",
]


def get_app_feature(hour: int, minute: int) -> str:
    """時刻から今回アピールするつむまね機能を選ぶ（ローテーション）"""
    index = (hour * 2 + (1 if minute >= 30 else 0)) % len(APP_FEATURES)
    return APP_FEATURES[index]


# ── Twitter文字数カウント ────────────────────────────────────
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


# ── Google News でトレンド収集 ────────────────────────────────
def gather_trend_headlines() -> list:
    """複数クエリのGoogle News RSSから今日のトレンドを収集"""
    queries = [
        "NISA 積立 おすすめ 2026",
        "日本株 急騰 注目銘柄",
        "iDeCo 節税 老後資金",
        "高配当株 配当利回り",
        "資産運用 初心者 始め方",
        "米国株 投資 注目",
        "新NISA 成長投資枠",
        "テーマ株 半導体 AI",
    ]
    headlines = []
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
        except Exception:
            continue

        for item in root.findall('.//item')[:2]:
            title_elem = item.find('title')
            if title_elem is None or not title_elem.text:
                continue
            title = title_elem.text.split(' - ')[0].strip()
            title = re.sub(r'【.*?】', '', title).strip()
            if title and title not in seen and len(title) > 5:
                seen.add(title)
                headlines.append(title)

    return headlines[:12]


# ── PHASE 2: X上のバズ投稿を分析（Basicプラン取得後に有効化）──
# def get_viral_x_posts() -> list:
#     bearer_token = os.environ.get("TWITTER_BEARER_TOKEN")
#     if not bearer_token:
#         return []
#     client = tweepy.Client(bearer_token=bearer_token)
#     keywords = ["日本株 NISA", "iDeCo 節税", "高配当株", "資産運用"]
#     viral = []
#     for kw in keywords:
#         try:
#             resp = client.search_recent_tweets(
#                 query=f"{kw} -is:retweet lang:ja",
#                 sort_order="relevancy",
#                 tweet_fields=["public_metrics", "text"],
#                 max_results=10
#             )
#             if resp.data:
#                 for tweet in resp.data:
#                     m = tweet.public_metrics
#                     score = m['like_count'] * 3 + m['retweet_count'] * 2 + m['reply_count']
#                     if score > 50:
#                         viral.append({"text": tweet.text, "score": score})
#         except Exception:
#             pass
#     viral.sort(key=lambda x: x["score"], reverse=True)
#     return [v["text"][:100] for v in viral[:5]]


# ── Claude API で投稿文を生成 ─────────────────────────────────
def generate_tweet(
    headlines: list,
    theme: dict,
    now: datetime,
    style_info: dict,
    feature: str,
) -> str | None:
    """Claude APIでトレンド×時間帯テーマ×スタイルに基づいた投稿を生成"""
    date_str = now.strftime('%-m月%-d日')
    time_str = now.strftime('%-H時%-M分')
    headlines_text = "\n".join(f"・{h}" for h in headlines)

    prompt = f"""あなたは日本の株式投資アプリ「つむまね」のSNSマネージャーです。
今は{date_str} {time_str}です。

━━ 今の時間帯: {theme['label']} ━━
この時間帯のフォーカス: {theme['focus']}
推奨フォーマット: {theme['format']}

━━ 今回の投稿スタイル: {style_info['label']} ━━
{style_info['instruction']}

━━ 今回アピールするつむまねの機能（必ず1文入れること） ━━
{feature}
→ 投稿の流れに合わせて自然に1文だけ入れる（ゴリ押しにならないように）

━━ 今日のトレンドニュース ━━
{headlines_text}

━━ 絶対に守るルール ━━
1. 文字数: 日本語1文字=2・英数字=1・URLは必ず23文字として計算し、合計【280以内】
2. 末尾に必ずこのURLをそのままコピー: {APP_URL}
3. ハッシュタグ3〜4個、必ず「#つむまね」を含める
4. 投稿文のみ出力（説明・前置き・「投稿文:」などは一切不要）
5. 前の投稿と異なる角度・切り口にすること

━━ 高インプレッションを出すコツ ━━
・数値・パーセンテージを入れる（年利3.5%・月1万円・○%増など）
・「知らないと損」「実は○○だった」「○○してみた」は反応が良い
・疑問形で始めると返信・引用が増える
・絵文字は冒頭と重要ポイントに適度に（多すぎ注意）
・ランキング形式（①②③）は保存率が高い
・アプリ紹介は自然な流れで、押しつけがましくなく

投稿文のみ出力してください。"""

    try:
        message = ai_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"⚠️ AI生成エラー: {e}")
        return None


# ── クリーニング＆バリデーション ─────────────────────────────
def clean_tweet(text: str) -> str:
    """AI出力から余計な説明文を除去"""
    for p in [r'^(投稿文|ツイート|X投稿|以下|出力)[：:]\s*', r'^```[^\n]*\n', r'\n```$']:
        text = re.sub(p, '', text, flags=re.MULTILINE).strip()
    text = re.sub(r'^[「」『』]', '', text).strip()
    return text


def validate_tweet(text: str) -> str | None:
    """URLと#つむまねの存在確認、文字数チェック"""
    if APP_URL not in text:
        print("  ✗ App StoreリンクなしでNG")
        return None
    if "#つむまね" not in text:
        print("  ✗ #つむまねなしでNG")
        return None
    length = tw_len(text)
    if length > MAX_CHARS:
        print(f"  ✗ {length}文字でNG（280超過）")
        return None
    return text


# ── メイン ────────────────────────────────────────────────
def main():
    # APIキー未設定の場合はエラーメールを送らず静かに終了
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠️ ANTHROPIC_API_KEY 未設定 - スキップします（エラーではありません）")
        sys.exit(0)

    global ai_client, twitter_client
    ai_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    twitter_client = tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )

    now = datetime.now(JST)
    hour = now.hour
    minute = now.minute

    theme = get_hour_theme(hour)
    style_info = get_post_style(minute)
    feature = get_app_feature(hour, minute)

    print(f"🤖 AI自動生成投稿 開始")
    print(f"  時刻: {now.strftime('%-H:%M')} / テーマ: {theme['label']}")
    print(f"  スタイル: {style_info['label']}")
    print(f"  機能アピール: {feature}")

    # 1. トレンド収集
    headlines = gather_trend_headlines()
    print(f"  トレンドニュース: {len(headlines)}件")

    if not headlines:
        print("❌ ニュース取得失敗 - スキップします")
        return

    # 2. AI生成（最大3回リトライ）
    tweet = None
    for attempt in range(1, 4):
        print(f"  AI生成 試行{attempt}/3...")
        raw = generate_tweet(headlines, theme, now, style_info, feature)
        if not raw:
            continue
        raw = clean_tweet(raw)
        tweet = validate_tweet(raw)
        if tweet:
            break
        print(f"    生成内容: {raw[:60]}...")

    if not tweet:
        print("❌ 3回試行失敗 - スキップします")
        return

    print(f"\n投稿内容({tw_len(tweet)}文字):\n{tweet}\n")

    # 3. 投稿
    try:
        response = twitter_client.create_tweet(text=tweet)
        print(f"✅ AI生成ツイート成功: ID={response.data['id']}")
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
