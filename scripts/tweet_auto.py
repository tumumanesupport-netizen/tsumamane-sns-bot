"""
AI自動生成投稿 - 30分ごと（48本/日）

3スタイルローテーション:
  (hour*2 + (1 if minute>=30 else 0)) % 3
  0 → 公式配信スタイル（今日のトレンド × データ断言系）
  1 → 個人コメントスタイル（体験・共感 × インフルエンサー過激口調）
  2 → 論争スタイル（投資界あるある議論に賛否で参加・炎上ぎりぎり）

文字数管理:
  URLとハッシュタグはコード側で付加。Claudeには本文のみ生成させる。
  超過した場合は末尾から1行ずつ削って強制収納。

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
    (5,  8,  "朝活タイム",     "今日の市場展望・前日米国株・朝イチ確認事項",   "朝活投資家向け"),
    (8,  12, "市場オープン",   "急騰急落銘柄・テーマ株・今日動きそうな銘柄",   "速報ランキング形式"),
    (12, 15, "お昼の相場",     "前場振り返り・後場注目点・テーマ株",           "中間レポート形式"),
    (15, 18, "引け後分析",     "本日まとめ・値動きの理由・明日への視点",       "分析考察形式"),
    (18, 24, "夜の学習タイム", "NISA・iDeCo・長期投資・高配当・資産運用基礎", "教育啓発形式"),
    (0,  5,  "深夜米国市場",   "米国株・ドル円・ナスダック・S&P500・翌日影響", "海外市場連動形式"),
]

# ── テーマ別ハッシュタグ（コード側で付加） ──────────────────────
THEME_HASHTAGS = {
    "朝活タイム":     "#朝活投資 #日本株 #市場展望 #つむまね",
    "市場オープン":   "#日本株 #急騰急落 #注目銘柄 #つむまね",
    "お昼の相場":     "#前場 #後場 #日本株 #つむまね",
    "引け後分析":     "#日本株 #相場分析 #投資 #つむまね",
    "夜の学習タイム": "#NISA #iDeCo #資産運用 #つむまね",
    "深夜米国市場":   "#米国株 #ドル円 #海外投資 #つむまね",
    "投資情報":       "#投資 #資産運用 #NISA #つむまね",
}

# ── つむまねの機能リスト ──────────────────────────────────────
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

# ── 論争スタイル用トピック ────────────────────────────────────
CONTROVERSIAL_TOPICS = [
    "「インデックス投資が最強」という投資界の定説",
    "「高配当株投資は効率が悪い」という意見",
    "「NISAは全員がやるべき」という常識",
    "「個別株より投資信託の方が良い」という風潮",
    "「長期積立投資なら負けない」という楽観論",
    "「日本株より米国株一択」という思い込み",
    "「FIREを目指すのが正解」という価値観",
    "「損切りは早い方が正解」という鉄則",
    "「iDeCoは節税になるから絶対お得」という常識",
    "「不動産より株の方が流動性が高くて良い」という主張",
    "「暗号資産はギャンブルで投資ではない」という見方",
    "「投資は若いうちから始めるほど正解」という常識",
    "「毎月の積立額より入金力を上げる方が大事」という意見",
    "「老後2000万円問題はNISAで解決できる」という楽観論",
    "「サラリーマンは副業より投資に集中すべき」という考え方",
]


def get_hour_theme(hour: int) -> dict:
    for start, end, label, focus, fmt in HOUR_THEMES:
        if start <= hour < end:
            return {"label": label, "focus": focus, "format": fmt}
    return {"label": "投資情報", "focus": "株式投資・NISA・資産運用", "format": "自由形式"}


def get_post_style(hour: int, minute: int) -> dict:
    """3スタイルローテーション: 公式 → 個人 → 論争"""
    index = (hour * 2 + (1 if minute >= 30 else 0)) % 3
    return [
        {"name": "official", "label": "公式配信スタイル"},
        {"name": "personal", "label": "個人コメントスタイル"},
        {"name": "debate",   "label": "論争スタイル"},
    ][index]


# ── フッター（URL＋ハッシュタグ）の構築と文字数計算 ─────────────
def build_footer(theme: dict) -> str:
    hashtags = THEME_HASHTAGS.get(theme["label"], THEME_HASHTAGS["投資情報"])
    return "\n" + APP_URL + "\n" + hashtags


def get_body_budget(footer: str) -> int:
    return MAX_CHARS - tw_len(footer) - 5


# ── Twitter文字数カウント ────────────────────────────────────
def tw_len(text: str) -> int:
    text = _URL_RE.sub("A" * 23, text)
    count = 0
    for ch in text:
        cp = ord(ch)
        if any([
            0x2E80 <= cp <= 0x303F, 0x3040 <= cp <= 0x31BF,
            0x3200 <= cp <= 0x33FF, 0x3400 <= cp <= 0x4DBF,
            0x4E00 <= cp <= 0x9FFF, 0xF900 <= cp <= 0xFAFF,
            0xFE30 <= cp <= 0xFE6F, 0xFF00 <= cp <= 0xFFEF,
        ]) or cp > 0xFFFF:
            count += 2
        else:
            count += 1
    return count


# ── RSS取得ユーティリティ ─────────────────────────────────────
def _fetch_rss_titles(url: str, limit: int = 3) -> list:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        titles = []
        for item in root.findall(".//item")[:limit]:
            t = item.find("title")
            if t is not None and t.text:
                title = t.text.split(" - ")[0].strip()
                title = re.sub(r"【.*?】|「.*?」", "", title).strip()
                if title and len(title) > 5:
                    titles.append(title)
        return titles
    except Exception:
        return []


def _gnews(query: str) -> str:
    return (
        "https://news.google.com/rss/search"
        "?q=" + query.replace(" ", "+") + "&hl=ja&gl=JP&ceid=JP:ja"
    )


# ── ニュース収集 ──────────────────────────────────────────────
def gather_market_news() -> list:
    queries = [
        "日経平均 株価 今日", "日本株 急騰 急落 注目銘柄",
        "NISA 新制度 2026", "iDeCo 節税 老後資金",
        "高配当株 配当利回り 人気", "米国株 ナスダック S&P500",
        "テーマ株 半導体 AI 防衛", "為替 ドル円 円安 円高",
        "日本銀行 金利 利上げ", "IPO 新規上場 注目",
    ]
    seen, result = set(), []
    for q in queries:
        for t in _fetch_rss_titles(_gnews(q), 2):
            if t not in seen:
                seen.add(t)
                result.append(t)
    return result[:15]


def gather_community_buzz() -> list:
    queries = [
        "NISA 始めた 体験 口コミ 実際", "個人投資家 資産 増えた 実感",
        "積立投資 継続 効果 実績", "高配当株 配当金 生活 サラリーマン",
        "iDeCo デメリット 知らなかった", "新NISA やってみた 正直",
        "株式投資 失敗 学んだ", "FIRE 目指す 投資 方法",
        "インデックス投資 積立 長期", "資産運用 初心者 変わった",
    ]
    seen, result = set(), []
    for q in queries:
        for t in _fetch_rss_titles(_gnews(q), 2):
            if t not in seen:
                seen.add(t)
                result.append(t)
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
#                     score = m["like_count"]*3 + m["retweet_count"]*2 + m["reply_count"]
#                     if score > 50:
#                         viral.append({"text": tweet.text, "score": score})
#         except Exception:
#             pass
#     viral.sort(key=lambda x: x["score"], reverse=True)
#     return [v["text"][:100] for v in viral[:5]]


# ── プロンプト生成 ──────────────────────────────────────────────
def _make_prompt_official(market_news, theme, date_str, features_text, body_budget):
    news_text = "\n".join("・" + n for n in market_news)
    jp_est = body_budget // 2
    return (
        "あなたは歯に衣着せない物言いで知られる投資メディアの論説編集長です。\n"
        "「業界の本音」「誰も言わない真実」を発信することで支持されています。\n"
        "今は" + date_str + "。テーマ: " + theme["label"] + "（" + theme["focus"] + "）\n\n"
        "━━ 今日のリアルタイム金融トレンド ━━\n"
        + news_text + "\n\n"
        "━━ 【絶対厳守】過激・断言スタイルで書くこと ━━\n"
        "おとなしい・無難な投稿は厳禁。必ず以下を守ること:\n\n"
        "【冒頭は必ずこのどれかで始める（必須）】\n"
        "・「○○しないと老後が詰む現実」\n"
        "・「9割の投資初心者が犯す致命的ミス」\n"
        "・「今すぐやめるべき○○」\n"
        "・「なぜ日本人は○○しないのか（衝撃）」\n"
        "・「知らないと一生損し続ける○○の真実」\n"
        "・「銀行が絶対に教えない○○」\n"
        "・「○○円以下で老後を迎えると詰む」\n"
        "・「知ってる人と知らない人、10年後の差がヤバい」\n\n"
        "【必ず入れること】\n"
        "・具体的な数字で現実の厳しさを突きつける（金額・年数・利率）\n"
        "・「知っている人 vs 知らない人」の格差を強調\n"
        "・断言・言い切り（弱腰表現「〜かもしれません」は絶対NG）\n"
        "・絵文字は📊💥🔥⚠️💸😱を必ず1個以上使う\n"
        "・ランキング（①②③）や「○○選」で保存率を上げる\n\n"
        "【絶対NG】\n"
        "・「〜かもしれません」「参考にしてください」などの丁寧すぎる表現\n"
        "・まとめるだけの無難な投稿\n"
        "・「ぜひご確認を」などのふわっとした締め\n\n"
        "━━ つむまねの機能を末尾に1文だけ自然に入れること ━━\n"
        "以下の中から最も自然に合う機能を1つ選んで「つむまね」アプリ名と一緒に紹介（URLは不要）:\n"
        + features_text + "\n\n"
        "━━ 生成ルール（厳守） ━━\n"
        "1. 【本文のみ】生成する（URLもハッシュタグも含めない・自動で付加します）\n"
        "2. 本文Twitterウェイトを【" + str(body_budget) + "以内】に収める\n"
        "   日本語1文字=2、英数字=1、絵文字=2 / 目安: 全角文字" + str(jp_est) + "文字以内\n"
        "3. 行数は最大6行（空行含む）\n"
        "4. 前の投稿と異なる切り口にすること\n"
        "5. 投稿文のみ出力（前置き・「投稿文:」などは一切不要）\n\n"
        "本文のみ出力してください。"
    )


def _make_prompt_personal(community_buzz, market_news, theme, date_str, features_text, body_budget):
    buzz_text = "\n".join("・" + b for b in community_buzz)
    news_sub  = "\n".join("・" + n for n in market_news[:4])
    jp_est = body_budget // 2
    return (
        "あなたはフォロワー数5万人以上の人気個人投資家インフルエンサーです。\n"
        "歯に衣着せぬ物言いで支持されており、「過激だけど本当のことを言う人」として知られています。\n"
        "今は" + date_str + "。テーマ: " + theme["label"] + "\n\n"
        "━━ 投資コミュニティで今話題になっていること ━━\n"
        "（投資家たちがSNSや口コミで語っているリアルな体験・関心事）\n"
        + buzz_text + "\n\n"
        "━━ 今日の市場（参考） ━━\n"
        + news_sub + "\n\n"
        "━━ 【絶対厳守】過激・挑発スタイルで書くこと ━━\n"
        "おとなしい・丁寧な投稿は厳禁。必ず以下を守ること:\n\n"
        "【冒頭は必ずこのどれかで始める（必須）】\n"
        "・「銀行に預けてるだけの人、マジで大丈夫？」\n"
        "・「NISAやらない理由が本当にわからない」\n"
        "・「〜しないやつの末路、見たくないな」\n"
        "・「これ言っていいのかわからんけど正直に言う」\n"
        "・「9割の人が気づいてない○○の事実」\n"
        "・「知らないと確実に損する話」\n"
        "・「今すぐやらないと後悔する理由」\n"
        "・「投資しない人と投資する人、5年後の差がヤバすぎる」\n\n"
        "【必ず入れること】\n"
        "・危機感・緊急性（「今すぐ」「手遅れになる前に」「〜な現実」）\n"
        "・具体的な数字で現実を突きつける\n"
        "・断言・言い切り（「〜だ」「〜しろ」口調）\n"
        "・絵文字は😤🔥💥😱🤯💸を必ず1個以上使う\n\n"
        "【絶対NG】\n"
        "・「〜かもしれません」「〜と思います」などの弱腰表現\n"
        "・おとなしくまとめるだけの無難な投稿\n"
        "・「参考にしてください」「ぜひ確認を」などの丁寧すぎる締め\n\n"
        "━━ つむまねの機能を末尾に1文だけ自然に入れること ━━\n"
        "以下の中から最も自然に合う機能を1つ選んで「つむまね」アプリ名と一緒に口コミ感覚で紹介（URLは不要）:\n"
        + features_text + "\n\n"
        "━━ 生成ルール（厳守） ━━\n"
        "1. 【本文のみ】生成する（URLもハッシュタグも含めない・自動で付加します）\n"
        "2. 本文Twitterウェイトを【" + str(body_budget) + "以内】に収める\n"
        "   日本語1文字=2、英数字=1、絵文字=2 / 目安: 全角文字" + str(jp_est) + "文字以内\n"
        "3. 行数は最大6行（空行含む）\n"
        "4. 前の投稿と異なる切り口にすること\n"
        "5. 投稿文のみ出力（前置き・「投稿文:」などは一切不要）\n\n"
        "本文のみ出力してください。"
    )


def _make_prompt_debate(market_news, now, features_text, body_budget):
    topic_index = (now.hour * 2 + (1 if now.minute >= 30 else 0)) % len(CONTROVERSIAL_TOPICS)
    topic = CONTROVERSIAL_TOPICS[topic_index]
    news_sub = "\n".join("・" + n for n in market_news[:5])
    date_str = now.strftime("%-m月%-d日")
    jp_est = body_budget // 2
    return (
        "あなたはフォロワー数5万人以上の個人投資家で、投資界隈のあるある論争に積極的に参加することで知られています。\n"
        "今は" + date_str + "。\n\n"
        "━━ 今回論じるテーマ ━━\n"
        + topic + "\n\n"
        "━━ 今日の市場（参考） ━━\n"
        + news_sub + "\n\n"
        "━━ 【絶対厳守】賛否を呼ぶ論争投稿のルール ━━\n"
        "・賛成 or 反対、どちらか一方を明確に選んで言い切る（日和見・中立は厳禁）\n"
        "・「こういう意見よく見るけど正直に言う」「〜論に物申す」的な切り口で入る\n"
        "・相手の主張の弱点を突くか、自分の体験で反論 or 支持する\n"
        "・「どっちが正しいかは人それぞれ」で絶対に終わらない\n"
        "・「それは○○の場合だけだ」「○○を無視してる」などの具体的な反論を入れる\n"
        "・最後は読者が「賛成」「反対」「俺は違う」と反応したくなる締めで終わる\n"
        "・絵文字は🔥💥🤔😤を使う\n\n"
        "【冒頭パターン例（このどれかで始める）】\n"
        "・「○○って言う人よく見るけどさ、正直言わせてもらう」\n"
        "・「○○論、俺はずっと疑問に思ってた」\n"
        "・「みんなが信じてる○○、本当に正しいの？」\n"
        "・「○○派の人に聞きたい、○○の場合はどうするの？」\n\n"
        "【絶対NG】\n"
        "・「どちらにも良い点があります」などの中立まとめ\n"
        "・「参考にしてください」「一概には言えません」の逃げ表現\n"
        "・賛否が分かれない当たり障りのない意見\n\n"
        "━━ つむまねの機能を末尾に1文だけ自然に入れること ━━\n"
        "以下の中から最も自然に合う機能を1つ選んで「つむまね」アプリ名と一緒に紹介（URLは不要）:\n"
        + features_text + "\n\n"
        "━━ 生成ルール（厳守） ━━\n"
        "1. 【本文のみ】生成する（URLもハッシュタグも含めない・自動で付加します）\n"
        "2. 本文Twitterウェイトを【" + str(body_budget) + "以内】に収める\n"
        "   日本語1文字=2、英数字=1、絵文字=2 / 目安: 全角文字" + str(jp_est) + "文字以内\n"
        "3. 行数は最大6行（空行含む）\n"
        "4. 投稿文のみ出力（前置き・「投稿文:」などは一切不要）\n\n"
        "本文のみ出力してください。"
    )


# ── Claude API で本文のみ生成 ─────────────────────────────────
def generate_body(market_news, community_buzz, theme, now, style_info, body_budget):
    date_str = now.strftime("%-m月%-d日 %-H時%-M分")
    features_text = "\n".join("  ・" + f for f in APP_FEATURES)
    style_name = style_info["name"]

    if style_name == "official":
        prompt = _make_prompt_official(market_news, theme, date_str, features_text, body_budget)
    elif style_name == "personal":
        prompt = _make_prompt_personal(community_buzz, market_news, theme, date_str, features_text, body_budget)
    else:  # debate
        prompt = _make_prompt_debate(market_news, now, features_text, body_budget)

    try:
        message = ai_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"AI生成エラー: {e}")
        return None


# ── クリーニング・トリム・バリデーション ─────────────────────
def clean_body(text: str) -> str:
    for p in [r"^(投稿文|ツイート|X投稿|以下|出力)[：:]\s*", r"^```[^\n]*\n", r"\n```$"]:
        text = re.sub(p, "", text, flags=re.MULTILINE).strip()
    text = re.sub(r"^[「」『』]", "", text).strip()
    text = _URL_RE.sub("", text).strip()
    lines = [l for l in text.split("\n") if not re.match(r"^#\S", l)]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def trim_body(body: str, budget: int) -> str:
    if tw_len(body) <= budget:
        return body
    lines = body.split("\n")
    while lines and tw_len("\n".join(lines)) > budget:
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                lines.pop(i)
                break
        else:
            lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
    return "\n".join(lines).strip()


def assemble_and_validate(body: str, footer: str) -> str | None:
    tweet = body + footer
    if APP_URL not in tweet:
        print("  URL なし NG")
        return None
    if "#つむまね" not in tweet:
        print("  #つむまね なし NG")
        return None
    length = tw_len(tweet)
    if length > MAX_CHARS:
        print(f"  {length}w NG（280超過）")
        return None
    return tweet


# ── メイン ────────────────────────────────────────────────
def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 未設定 - スキップ（エラーではありません）")
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
    style_info = get_post_style(hour, minute)
    footer     = build_footer(theme)
    budget     = get_body_budget(footer)

    print(f"AI自動生成投稿 開始")
    print(f"  {now.strftime('%-H:%M')} / {theme['label']} / {style_info['label']}")
    print(f"  本文上限: {budget}w (footer={tw_len(footer)}w)")

    market_news    = gather_market_news()
    community_buzz = gather_community_buzz() if style_info["name"] in ("personal", "debate") else []
    print(f"  ニュース: {len(market_news)}件 / buzz: {len(community_buzz)}件")

    if not market_news:
        print("ニュース取得失敗 - スキップ")
        return

    tweet = None
    for attempt in range(1, 4):
        print(f"  AI生成 {attempt}/3...")
        raw = generate_body(market_news, community_buzz, theme, now, style_info, budget)
        if not raw:
            continue
        body  = clean_body(raw)
        body  = trim_body(body, budget)
        tweet = assemble_and_validate(body, footer)
        if tweet:
            break

    if not tweet:
        print("3回失敗 - スキップ")
        return

    print(f"\n投稿内容 ({tw_len(tweet)}w):\n{tweet}\n")

    try:
        response = twitter_client.create_tweet(text=tweet)
        print(f"ツイート成功: ID={response.data['id']}")
    except tweepy.errors.Forbidden as e:
        print(f"403 Forbidden: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"  本文: {e.response.text}")
        raise
    except Exception as e:
        print(f"エラー: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()
