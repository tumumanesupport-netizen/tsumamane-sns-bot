"""
AI自動生成投稿 - 30分ごと（48本/日）

スタイル交互:
  :00 → 公式配信スタイル
        今日の金融トレンドニュースをデータ・断言系で発信
  :30 → 個人コメントスタイル
        投資コミュニティで話題の体験談・声をインフルエンサー口調で発信

つむまね機能:
  8種の機能から投稿内容に最も自然に合うものをClaudeが選んで挿入

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
    for start, end, label, focus, fmt in HOUR_THEMES:
        if start <= hour < end:
            return {"label": label, "focus": focus, "format": fmt}
    return {"label": "投資情報", "focus": "株式投資・NISA・資産運用", "format": "自由形式"}


# ── 投稿スタイル（:00=公式 / :30=個人コメント） ────────────────
POST_STYLES = {
    "official": {
        "name": "official",
        "label": "公式配信スタイル",
    },
    "personal": {
        "name": "personal",
        "label": "個人コメントスタイル",
    },
}


def get_post_style(minute: int) -> dict:
    return POST_STYLES["personal"] if minute >= 30 else POST_STYLES["official"]


# ── つむまねの機能リスト（Claudeが最適なものを1つ選ぶ） ──────────
APP_FEATURES = [
    "複数の証券口座（SBI・楽天・マネックス・松井など）をまとめて一括管理できる",
    "全口座の資産残高を一画面でリアルタイム把握できる",
    "老後の資産を将来シミュレーションで確認できる",
    "NISA・iDeCo口座の残高もひとまとめに確認できる",
    "配当金・分配金の受取履歴を口座横断で自動管理できる",
    "保有株のポートフォリオをグラフで可視化できる",
    "各口座の損益をリアルタイムで横断比較できる",
    "投資初心者でも直感的に使えるシンプルなUIで資産管理できる",
]


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


# ── RSS取得ユーティリティ ─────────────────────────────────────
def _fetch_rss_titles(url: str, limit: int = 3) -> list[str]:
    """RSSフィードからタイトルを取得（失敗時は空リスト）"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        titles = []
        for item in root.findall('.//item')[:limit]:
            t = item.find('title')
            if t is not None and t.text:
                title = t.text.split(' - ')[0].strip()
                title = re.sub(r'【.*?】|「.*?」', '', title).strip()
                if title and len(title) > 5:
                    titles.append(title)
        return titles
    except Exception:
        return []


def _google_news_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search"
        f"?q={query.replace(' ', '+')}&hl=ja&gl=JP&ceid=JP:ja"
    )


# ── ① 公式配信用: 金融トレンドニュース ─────────────────────────
def gather_market_news() -> list[str]:
    """金融・経済の最新ニュースを幅広く収集（公式スタイル向け）"""
    queries = [
        "日経平均 株価 今日",
        "日本株 急騰 急落 注目銘柄",
        "NISA 新制度 2026",
        "iDeCo 節税 老後資金",
        "高配当株 配当利回り 人気",
        "米国株 ナスダック S&P500",
        "テーマ株 半導体 AI 防衛",
        "為替 ドル円 円安 円高",
        "日本銀行 金利 利上げ",
        "IPO 新規上場 注目",
    ]
    headlines = []
    seen = set()
    for q in queries:
        for title in _fetch_rss_titles(_google_news_url(q), limit=2):
            if title not in seen:
                seen.add(title)
                headlines.append(title)
    return headlines[:15]


# ── ② 個人コメント用: 投資コミュニティの声・体験談 ──────────────
def gather_community_buzz() -> list[str]:
    """投資家コミュニティで話題の体験談・口コミ系ニュースを収集（個人スタイル向け）"""
    queries = [
        "NISA 始めた 体験 口コミ 実際",
        "個人投資家 資産 増えた 実感",
        "積立投資 継続 効果 実績",
        "高配当株 配当金 生活 サラリーマン",
        "iDeCo デメリット 知らなかった",
        "新NISA やってみた 正直",
        "株式投資 失敗 学んだ",
        "資産運用 初心者 変わった 生活",
        "FIRE 目指す 投資 方法",
        "インデックス投資 積立 長期",
    ]
    buzz = []
    seen = set()
    for q in queries:
        for title in _fetch_rss_titles(_google_news_url(q), limit=2):
            if title not in seen:
                seen.add(title)
                buzz.append(title)
    return buzz[:15]


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
    market_news: list[str],
    community_buzz: list[str],
    theme: dict,
    now: datetime,
    style_info: dict,
) -> str | None:
    """スタイルに応じてニュースソースとプロンプトを切り替えて投稿文を生成"""

    date_str = now.strftime('%-m月%-d日')
    time_str = now.strftime('%-H時%-M分')
    features_text = "\n".join(f"  ・{f}" for f in APP_FEATURES)

    is_personal = style_info["name"] == "personal"

    if is_personal:
        # ── 個人コメントスタイル ──────────────────────────────
        buzz_text = "\n".join(f"・{b}" for b in community_buzz)
        news_sub  = "\n".join(f"・{n}" for n in market_news[:5])

        prompt = f"""あなたはフォロワー数5万人以上の人気個人投資家インフルエンサーです。
今は{date_str} {time_str}。テーマ時間帯: {theme['label']}

━━ 今、投資コミュニティで話題になっていること ━━
（これらは投資家たちが実際に語っているリアルな体験・関心事のトレンドです）
{buzz_text}

━━ 今日の市場の動き（参考） ━━
{news_sub}

━━ あなたの投稿スタイル ━━
・フォロワーへの「語りかけ」や「共感呼びかけ」が上手い
・「正直〜」「これ知らなかった😅」「みんなも気になってるはず」「〜してみた結果」など
  体験談・気づき・驚きを混ぜる
・数字や体験に基づくリアルさが信頼感を生む
・絵文字は😅🤔💡🙌✨😮を感情に合わせて自然に使う
・上から目線にならず、同じ投資家目線で話す
・「最近こんな声をよく聞くんだけど〜」「投資仲間と話してたら〜」みたいな語り口もOK

━━ つむまねの機能を1文だけ自然に入れること ━━
以下の中から投稿内容に最も自然に合う機能を1つだけ選んで、
「つむまね」というアプリ名と一緒に口コミ感覚で紹介する:
{features_text}

━━ 絶対に守るルール ━━
1. 文字数: 日本語1文字=2・英数字=1・URLは必ず23文字として計算、合計【280以内】
2. 末尾に必ずこのURLをそのままコピー: {APP_URL}
3. ハッシュタグ3〜4個、必ず「#つむまね」を含める
4. 投稿文のみ出力（前置き・説明・「投稿文:」などは一切不要）
5. 前の投稿と異なる切り口にすること

投稿文のみ出力してください。"""

    else:
        # ── 公式配信スタイル ──────────────────────────────────
        news_text = "\n".join(f"・{n}" for n in market_news)

        prompt = f"""あなたは権威ある投資情報メディアの編集長です。
今は{date_str} {time_str}。テーマ時間帯: {theme['label']}（{theme['focus']}）

━━ 今日のリアルタイム金融トレンド（これをベースに投稿を作成） ━━
{news_text}

━━ 公式配信スタイルの要件 ━━
・上記のトレンドの中から最も今日インパクトのある話題を選んで発信
・「〜が重要です」「〜を押さえておきましょう」「〜のポイントをまとめました」など
  断言・まとめ系の権威ある語り口
・数字・パーセンテージ・具体的事実を積極的に使う（例: 年利3.5%・+○%・○億円）
・絵文字は📊📈📉💹🔔📰💰など情報・金融系を使う
・ランキング（①②③）や箇条書きは保存率・シェア率が高い
・今日のニュースに直接触れた「時事性」が命

━━ つむまねの機能を1文だけ自然に入れること ━━
以下の中から投稿内容に最も自然に合う機能を1つだけ選んで、
「つむまね」というアプリ名と一緒に権威ある紹介文として添える:
{features_text}

━━ 絶対に守るルール ━━
1. 文字数: 日本語1文字=2・英数字=1・URLは必ず23文字として計算、合計【280以内】
2. 末尾に必ずこのURLをそのままコピー: {APP_URL}
3. ハッシュタグ3〜4個、必ず「#つむまね」を含める
4. 投稿文のみ出力（前置き・説明・「投稿文:」などは一切不要）
5. 前の投稿と異なる切り口にすること

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
    for p in [r'^(投稿文|ツイート|X投稿|以下|出力)[：:]\s*', r'^```[^\n]*\n', r'\n```$']:
        text = re.sub(p, '', text, flags=re.MULTILINE).strip()
    text = re.sub(r'^[「」『』]', '', text).strip()
    return text


def validate_tweet(text: str) -> str | None:
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
    hour, minute = now.hour, now.minute
    theme      = get_hour_theme(hour)
    style_info = get_post_style(minute)

    print(f"🤖 AI自動生成投稿 開始")
    print(f"  時刻: {now.strftime('%-H:%M')} / テーマ: {theme['label']} / スタイル: {style_info['label']}")

    # 1. トレンド収集（スタイルに応じて使い分け）
    print("  ニュース収集中...")
    market_news    = gather_market_news()
    community_buzz = gather_community_buzz() if style_info["name"] == "personal" else []
    print(f"  市場ニュース: {len(market_news)}件 / コミュニティBuzz: {len(community_buzz)}件")

    if not market_news:
        print("❌ ニュース取得失敗 - スキップします")
        return

    # 2. AI生成（最大3回リトライ）
    tweet = None
    for attempt in range(1, 4):
        print(f"  AI生成 試行{attempt}/3...")
        raw = generate_tweet(market_news, community_buzz, theme, now, style_info)
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
