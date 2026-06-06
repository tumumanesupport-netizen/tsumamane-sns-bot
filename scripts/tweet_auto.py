"""
⑦ AI自動生成投稿 - 毎朝9:00 JST
Google News でトレンドを収集 → Claude API で投稿文を自動生成・投稿

PHASE 1（現在）: Google News トレンド → Claude API 生成
PHASE 2（X Basic plan取得後）: X 上のバズ投稿も分析して精度UP
  → get_viral_x_posts() のコメントアウトを外して有効化
"""
import os
import re
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

twitter_client = tweepy.Client(
    consumer_key=os.environ["TWITTER_API_KEY"],
    consumer_secret=os.environ["TWITTER_API_SECRET"],
    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
    access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
)

ai_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


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


# ── PHASE 1: Google News でトレンド収集 ──────────────────────
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
#     """X検索APIでバズ投稿を取得（X API Basicプラン必要）"""
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
def generate_tweet(headlines: list, viral_posts: list = None) -> str | None:
    """Claude APIでトレンドに基づいた高インプレッション投稿を生成"""
    today = datetime.now(JST).strftime('%-m月%-d日（%a）')
    headlines_text = "\n".join(f"・{h}" for h in headlines)

    viral_section = ""
    if viral_posts:
        viral_text = "\n".join(f"・{p}" for p in viral_posts)
        viral_section = f"""
## 今日Xでバズっている投稿（参考）
{viral_text}
"""

    prompt = f"""あなたは日本の株式投資アプリ「つむまね」のSNSマネージャーです。
今日は{today}です。個人投資家・NISA初心者・投資中級者をターゲットにしています。

以下のトレンドニュースを参考に、Xで高いインプレッションを獲得できる投稿文を1つ作成してください。
{viral_section}
## 今日のトレンドニュース
{headlines_text}

## 絶対に守るルール
1. 文字数: 日本語1文字=2、英数字=1、URLは必ず23文字として計算し、合計280以内
2. 末尾に必ずこのURL（URLはそのままコピー）: {APP_URL}
3. ハッシュタグ3〜4個、最後に必ず「#つむまね」を含める
4. 投稿文のみ出力（説明・コメント・「投稿文:」などの前置き一切不要）

## 高インプレッションを出すコツ
- 数値・パーセンテージを入れると信頼感UP（例: 年利3.5%、月1万円）
- 「知らないと損」「○○してみた」「実は○○だった」は反応が良い
- 疑問形で始めると返信・引用が増える
- 絵文字は冒頭と重要ポイントに1〜2個（多すぎ注意）
- ランキング形式（①②③）は保存率が高い
- ニュースへの「自分の意見・コメント」があると差別化になる
- アプリ紹介は押しつけがましくなく、自然な流れで

## 参考フォーマット（いずれか1つを選んで応用）
A) 疑問形+データ: 「○○って知ってた？\n実は...\n\n詳しくはアプリで確認👇\n[URL]\n#タグ」
B) ランキング: 「今週注目の○○TOP3🔥\n①...\n②...\n③...\n\nつむまねで全銘柄チェック📱\n[URL]\n#タグ」
C) 驚き+解説: 「○○が△△！\nその理由は...\n\n[URL]\n#タグ」
D) 呼びかけ型: 「NISAを始めたい人へ📣\n・...\n・...\n・...\n[URL]\n#タグ」

今日のニュースを参考に、上記以外の独自のアイデアも歓迎。"""

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


# ── 生成テキストのクリーニング ────────────────────────────────
def clean_tweet(text: str) -> str:
    """AI出力から余計な説明文を除去"""
    # 「投稿文：」などの前置きを除去
    patterns = [
        r'^(投稿文|ツイート|X投稿|以下|出力)[：:]\s*',
        r'^```[^\n]*\n', r'\n```$',
    ]
    for p in patterns:
        text = re.sub(p, '', text, flags=re.MULTILINE).strip()
    # 先頭が「」や「」なら除去
    text = re.sub(r'^[「」『』]', '', text).strip()
    return text


# ── バリデーション ────────────────────────────────────────────
def validate_tweet(text: str) -> str | None:
    """URLと#つむまねの存在確認、文字数チェック"""
    if APP_URL not in text:
        print(f"  ✗ App StoreリンクなしでNG")
        return None
    if "#つむまね" not in text:
        print(f"  ✗ #つむまねなしでNG")
        return None
    length = tw_len(text)
    if length > MAX_CHARS:
        print(f"  ✗ {length}文字でNG（280超過）")
        return None
    return text


# ── メイン ────────────────────────────────────────────────
def main():
    print("🤖 AI自動生成投稿 開始...")

    # 1. トレンド収集
    headlines = gather_trend_headlines()
    print(f"  トレンドニュース: {len(headlines)}件")
    for h in headlines:
        print(f"    - {h}")

    if not headlines:
        print("❌ ニュース取得失敗 - スキップします")
        return

    # PHASE 2: バズ投稿を追加（有効化するにはコメントアウトを外す）
    # viral_posts = get_viral_x_posts()
    viral_posts = []

    # 2. AI生成（最大3回リトライ）
    tweet = None
    for attempt in range(1, 4):
        print(f"  AI生成 試行{attempt}/3...")
        raw = generate_tweet(headlines, viral_posts)
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
