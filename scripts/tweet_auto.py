"""
AI自動生成投稿 - 30分ごと（48本/日）

文字数管理:
  URLとハッシュタグはコード側で付加。
  Claudeには本文のみを生成させ、ウェイト上限を明示して超過を防ぐ。
  それでも超過した場合は末尾から1行ずつ削って強制収納。

スタイル交互:
  :00 → 公式配信スタイル（市場ニュース × データ断言系）
  :30 → 個人コメントスタイル（コミュニティ体験談 × インフルエンサー口調）

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

# ── 時間帯別テーマ ────────────────────────────────────────────
HOUR_THEMES = [
    (5,  8,  "朝活タイム",
     "今日の市場展望・前日の米国株動向・朝イチで確認すべきこと",
     "朝活投資家向け"),
    (8,  12, "市場オープン",
     "急騰急落銘柄・テーマ株・今日動きそうな銘柄・出来高",
     "速報・ランキング形式"),
    (12, 15, "お昼の相場",
     "前場の振り返り・後場の注目点・今日のテーマ株",
     "中間レポート形式"),
    (15, 18, "引け後分析",
     "本日の相場まとめ・値動きの理由・明日への視点",
     "分析・考察形式"),
    (18, 24, "夜の学習タイム",
     "NISA・iDeCo・長期投資・高配当・資産運用の基礎",
     "教育・啓発形式"),
    (0,  5,  "深夜・米国市場",
     "米国株・ドル円・ナスダック・S&P500・翌日の日本市場への影響",
     "海外市場連動形式"),
]

# ── テーマ別ハッシュタグ（コード側で付加・Claudeには生成させない）──
THEME_HASHTAGS = {
    "朝活タイム":     "#朝活投資 #日本株 #市場展望 #つむまね",
    "市場オープン":   "#日本株 #急騰急落 #注目銘柄 #つむまね",
    "お昼の相場":     "#前場 #後場 #日本株 #つむまね",
    "引け後分析":     "#日本株 #相場分析 #投資 #つむまね",
    "夜の学習タイム": "#NISA #iDeCo #資産運用 #つむまね",
    "深夜・米国市場": "#米国株 #ドル円 #海外投資 #つむまね",
    "投資情報":       "#投資 #資産運用 #NISA #つむまね",
}

# ── つむまねの機能リスト（Claudeが文脈に合う1つを選んで1文入れる）──
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


def get_hour_theme(hour: int) -> dict:
    for start, end, label, focus, fmt in HOUR_THEMES:
        if start <= hour < end:
            return {"label": label, "focus": focus, "format": fmt}
    return {"label": "投資情報", "focus": "株式投資・NISA・資産運用", "format": "自由形式"}


def get_post_style(minute: int) -> dict:
    if minute >= 30:
        return {"name": "personal", "label": "個人コメントスタイル"}
    return {"name": "official", "label": "公式配信スタイル"}


# ── フッター（URL＋ハッシュタグ）の構築と文字数計算 ─────────────
def build_footer(theme: dict) -> str:
    """URLとハッシュタグをコード側で組み立てる"""
    hashtags = THEME_HASHTAGS.get(theme['label'], THEME_HASHTAGS['投資情報'])
    return f"\n{APP_URL}\n{hashtags}"


def get_body_budget(footer: str) -> int:
    """本文に使える最大ウェイト文字数（安全マージン5込み）"""
    return MAX_CHARS - tw_len(footer) - 5


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


def _gnews(query: str) -> str:
    return (
        "https://news.google.com/rss/search"
        f"?q={query.replace(' ', '+')}&hl=ja&gl=JP&ceid=JP:ja"
    )


# ── ニュース収集 ──────────────────────────────────────────────
def gather_market_news() -> list[str]:
    """公式スタイル向け: 金融・経済の最新ニュース"""
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
    seen, result = set(), []
    for q in queries:
        for t in _fetch_rss_titles(_gnews(q), 2):
            if t not in seen:
                seen.add(t); result.append(t)
    return result[:15]


def gather_community_buzz() -> list[str]:
    """個人スタイル向け: 投資コミュニティの体験談・口コミ系"""
    queries = [
        "NISA 始めた 体験 口コミ 実際",
        "個人投資家 資産 増えた 実感",
        "積立投資 継続 効果 実績",
        "高配当株 配当金 生活 サラリーマン",
        "iDeCo デメリット 知らなかった",
        "新NISA やってみた 正直",
        "株式投資 失敗 学んだ",
        "FIRE 目指す 投資 方法",
        "インデックス投資 積立 長期",
        "資産運用 初心者 変わった",
    ]
    seen, result = set(), []
    for q in queries:
        for t in _fetch_rss_titles(_gnews(q), 2):
            if t not in seen:
                seen.add(t); result.append(t)
    return result[:15]


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
#                     score = m['like_count']*3 + m['retweet_count']*2 + m['reply_count']
#                     if score > 50:
#                         viral.append({"text": tweet.text, "score": score})
#         except Exception:
#             pass
#     viral.sort(key=lambda x: x["score"], reverse=True)
#     return [v["text"][:100] for v in viral[:5]]


# ── Claude API で本文のみ生成 ─────────────────────────────────
def generate_body(
    market_news: list[str],
    community_buzz: list[str],
    theme: dict,
    now: datetime,
    style_info: dict,
    body_budget: int,
) -> str | None:
    """
    本文のみを生成（URLとハッシュタグはコード側で付加するので含めない）。
    body_budget: 本文に使えるTwitterウェイト上限
    """
    date_str = now.strftime('%-m月%-d日')
    time_str = now.strftime('%-H時%-M分')
    features_text = "\n".join(f"  ・{f}" for f in APP_FEATURES)
    is_personal = style_info["name"] == "personal"

    # 本文サイズ感の日本語目安（全角換算）
    jp_char_estimate = body_budget // 2

    if is_personal:
        buzz_text = "\n".join(f"・{b}" for b in community_buzz)
        news_sub  = "\n".join(f"・{n}" for n in market_news[:4])
        role_and_style = f"""あなたはフォロワー数5万人以上の人気個人投資家インフルエンサーです。
歯に衣着せぬ物言いで支持されており、「過激だけど本当のことを言う人」として知られています。
今は{date_str} {time_str}。テーマ: {theme['label']}

━━ 投資コミュニティで今話題になっていること ━━
（投資家たちがSNSや口コミで語っているリアルな体験・関心事）
{buzz_text}

━━ 今日の市場（参考） ━━
{news_sub}

━━ 【絶対厳守】過激・挑発スタイルで書くこと ━━
おとなしい・丁寧な投稿は厳禁。必ず以下を守ること:

【冒頭は必ずこのどれかで始める（必須）】
・「銀行に預けてるだけの人、マジで大丈夫？」
・「NISAやらない理由が本当にわからない」
・「〜しないやつの末路、見たくないな」
・「これ言っていいのかわからんけど正直に言う」
・「9割の人が気づいてない〇〇の事実」
・「知らないと確実に損する話」
・「今すぐやらないと後悔する理由」
・「投資しない人と投資する人、5年後の差がヤバすぎる」

【必ず入れること】
・危機感・緊急性（「今すぐ」「手遅れになる前に」「〜な現実」）
・具体的な数字で現実を突きつける
・断言・言い切り（「〜です」「〜します」ではなく「〜だ」「〜しろ」口調）
・絵文字は😤🔥💥😱🤯💸を必ず1個以上使う

【絶対NG】
・「〜かもしれません」「〜と思います」などの弱腰表現
・おとなしくまとめるだけの無難な投稿
・「参考にしてください」「ぜひ確認を」などの丁寧すぎる締め"""
    else:
        news_text = "\n".join(f"・{n}" for n in market_news)
        role_and_style = f"""あなたは歯に衣着せない物言いで知られる投資メディアの論説編集長です。
「業界の本音」「誰も言わない真実」を発信することで支持されています。
今は{date_str} {time_str}。テーマ: {theme['label']}（{theme['focus']}）

━━ 今日のリアルタイム金融トレンド ━━
{news_text}

━━ 【絶対厳守】過激・断言スタイルで書くこと ━━
おとなしい・無難な投稿は厳禁。必ず以下を守ること:

【冒頭は必ずこのどれかで始める（必須）】
・「〇〇しないと老後が詰む現実」
・「9割の投資初心者が犯す致命的ミス」
・「今すぐやめるべき〇〇」
・「なぜ日本人は〇〇しないのか（衝撃）」
・「知らないと一生損し続ける〇〇の真実」
・「銀行が絶対に教えない〇〇」
・「〇〇円以下で老後を迎えると詰む」
・「知ってる人と知らない人、10年後の差がヤバい」

【必ず入れること】
・具体的な数字で現実の厳しさを突きつける（金額・年数・利率）
・「知っている人 vs 知らない人」の格差・格差の拡大
・断言・言い切り（弱腰表現「〜かもしれません」は絶対NG）
・絵文字は📊💥🔥⚠️💸😱を必ず1個以上使う
・ランキング（①②③）や「〇〇選」で保存率を上げる

【絶対NG】
・「〜かもしれません」「参考にしてください」などの丁寧すぎる表現
・まとめるだけの無難な投稿・当たり障りのない内容
・「ぜひご確認を」などのふわっとした締め"""

    prompt = f"""{role_and_style}

━━ つむまねの機能を末尾に1文だけ自然に入れること ━━
以下の中から投稿内容に最も自然に合う機能を1つだけ選んで、
「つむまね」というアプリ名と一緒に紹介する（URLは不要）:
{features_text}

━━ 生成ルール（厳守） ━━
1. 【本文のみ】を生成する
   - URLは含めない（自動で付加します）
   - ハッシュタグ（#で始まる語）は含めない（自動で付加します）
2. 本文のTwitterウェイト文字数を【{body_budget}以内】に収める
   - 日本語1文字=2、英数字=1、絵文字=2で計算
   - 目安: 全角文字{jp_char_estimate}文字以内
3. 行数は最大6行（空行含む）
4. 前の投稿と異なる切り口にすること
5. 投稿文のみ出力（前置き・説明・「投稿文:」などは一切不要）

本文のみ出力してください。"""

    try:
        message = ai_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"⚠️ AI生成エラー: {e}")
        return None


# ── クリーニング・トリム・バリデーション ─────────────────────
def clean_body(text: str) -> str:
    """AIが誤って入れたURL・ハッシュタグ・前置きを除去"""
    # 前置き除去
    for p in [r'^(投稿文|ツイート|X投稿|以下|出力)[：:]\s*', r'^```[^\n]*\n', r'\n```$']:
        text = re.sub(p, '', text, flags=re.MULTILINE).strip()
    text = re.sub(r'^[「」『』]', '', text).strip()
    # URLを除去（コード側で付加するため）
    text = _URL_RE.sub('', text).strip()
    # ハッシュタグ行を除去
    lines = [l for l in text.split('\n') if not re.match(r'^#\S', l)]
    text = '\n'.join(lines).strip()
    # 末尾の空行を整理
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


def trim_body(body: str, budget: int) -> str:
    """本文がbudgetを超えていたら末尾の行から削る"""
    if tw_len(body) <= budget:
        return body
    lines = body.split('\n')
    while lines and tw_len('\n'.join(lines)) > budget:
        # 末尾から非空行を1行削る
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                lines.pop(i)
                break
        else:
            lines.pop()
        # 末尾の連続空行を削る
        while lines and not lines[-1].strip():
            lines.pop()
    return '\n'.join(lines).strip()


def assemble_and_validate(body: str, footer: str) -> str | None:
    """本文＋フッターを合わせてバリデーション"""
    tweet = body + footer
    if APP_URL not in tweet:
        print("  ✗ URLなしでNG")
        return None
    if "#つむまね" not in tweet:
        print("  ✗ #つむまねなしでNG")
        return None
    length = tw_len(tweet)
    if length > MAX_CHARS:
        print(f"  ✗ {length}文字でNG（280超過）")
        return None
    return tweet


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
    footer     = build_footer(theme)
    budget     = get_body_budget(footer)

    print(f"🤖 AI自動生成投稿 開始")
    print(f"  時刻: {now.strftime('%-H:%M')} / テーマ: {theme['label']} / スタイル: {style_info['label']}")
    print(f"  本文ウェイト上限: {budget}（フッター={tw_len(footer)}、合計上限={MAX_CHARS}）")

    # 1. トレンド収集
    print("  ニュース収集中...")
    market_news    = gather_market_news()
    community_buzz = gather_community_buzz() if style_info["name"] == "personal" else []
    print(f"  市場ニュース: {len(market_news)}件 / コミュニティBuzz: {len(community_buzz)}件")

    if not market_news:
        print("❌ ニュース取得失敗 - スキップします")
        return

    # 2. AI生成（最大3回）→ クリーニング → トリム → バリデーション
    tweet = None
    for attempt in range(1, 4):
        print(f"  AI生成 試行{attempt}/3...")
        raw = generate_body(market_news, community_buzz, theme, now, style_info, budget)
        if not raw:
            continue

        body = clean_body(raw)
        body = trim_body(body, budget)          # 超過していれば強制短縮
        tweet = assemble_and_validate(body, footer)

        if tweet:
            break
        print(f"    本文({tw_len(body)}w): {body[:50]}...")

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
