"""
④ IPO情報投稿 - 直近上場予定（TOP3）＋最新ニュース
スケジュール出所: ipojp.com
ニュース出所: Google News RSS
投稿タイミング: 毎週月曜 朝7時 JST（GitHub Actions: 日曜UTC22:00）
"""
import os
import re
import tweepy
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date
import pytz
import xml.etree.ElementTree as ET

JST = pytz.timezone('Asia/Tokyo')
APP_URL = "https://apps.apple.com/jp/app/id6773302106"
MAX_CHARS = 280
CIRCLED = "①②③④⑤"
_URL_RE = re.compile(r'https?://\S+')

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

client = tweepy.Client(
    consumer_key=os.environ["TWITTER_API_KEY"],
    consumer_secret=os.environ["TWITTER_API_SECRET"],
    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
    access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
)


# ── Twitter文字数カウント ───────────────────────────────────────
def tw_len(text: str) -> int:
    """Twitter加重文字数（日本語・絵文字=2文字、URL=23文字として計算）"""
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


# ── IPOスケジュール取得（ipojp.com） ─────────────────────────────
def get_ipo_schedule(limit: int = 3) -> list:
    """今後上場予定のIPO銘柄を上場日順で取得"""
    url = "https://ipojp.com/schedule/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️ IPOスケジュール取得エラー: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    today = date.today()
    ipos = []
    seen = set()

    # 日付パターン（例: 2026/06/30）にマッチするテキストを起点に周辺情報を取得
    date_pattern = re.compile(r'(\d{4})/(\d{2})/(\d{2})')

    for text_node in soup.find_all(string=date_pattern):
        m = date_pattern.search(str(text_node))
        if not m:
            continue
        try:
            listing_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue

        if listing_date < today:
            continue  # 上場済みはスキップ

        # 近くにある銘柄名リンクを探す（親要素を順に遡る）
        parent = getattr(text_node, 'parent', None)
        name, market, price = "", "", ""

        for _ in range(8):
            if parent is None:
                break
            full_text = parent.get_text(" ", strip=True)

            # 銘柄名リンク（/schedule/XXXXX/ 形式）
            if not name:
                for a in parent.find_all('a', href=re.compile(r'/schedule/\d+')):
                    candidate = a.get_text(strip=True)
                    if candidate and len(candidate) <= 20:
                        name = candidate
                        break

            # 市場区分（省略形で文字数節約）
            if not market:
                for kw, abbr in [("グロース", "グロ"), ("スタンダード", "スタ"), ("プライム", "プラ")]:
                    if kw in full_text:
                        market = abbr
                        break

            # 公開価格
            if not price:
                pm = re.search(r'公開価格[：:]\s*([\d,]+)', full_text)
                if pm:
                    price = pm.group(1).replace(",", "") + "円"

            if name and market:
                break
            parent = getattr(parent, 'parent', None)

        if not name or (name, listing_date) in seen:
            continue

        seen.add((name, listing_date))
        ipos.append({
            "name": name,
            "date": listing_date,
            "market": market,
            "price": price,
        })

    ipos.sort(key=lambda x: x["date"])
    return ipos[:limit]


# ── IPO最新ニュース取得（Google News RSS） ────────────────────────
def get_ipo_news(limit: int = 1) -> list:
    """Google News RSSからIPO関連の最新ニュースを取得"""
    rss_url = (
        "https://news.google.com/rss/search"
        "?q=IPO+新規上場+日本株&hl=ja&gl=JP&ceid=JP:ja"
    )
    try:
        resp = requests.get(rss_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"⚠️ ニュース取得エラー: {e}")
        return []

    news = []
    for item in root.findall('.//item')[:limit * 3]:
        title_elem = item.find('title')
        if title_elem is None or not title_elem.text:
            continue
        # "タイトル - 媒体名" から媒体名を除去
        title = title_elem.text.split(' - ')[0].strip()
        # 不要なワードを除去してコンパクトに
        title = re.sub(r'【.*?】', '', title).strip()
        if len(title) > 24:
            title = title[:23] + '…'
        if title:
            news.append(title)
        if len(news) >= limit:
            break

    return news


# ── ツイート生成 ───────────────────────────────────────────────
def build_tweet(ipos: list, news: list, max_name: int = 99) -> str:
    today_str = datetime.now(JST).strftime('%-m/%-d')
    lines = [f"📋 {today_str} 注目IPO情報"]

    if ipos:
        lines.append("🗓 直近上場予定")
        for i, ipo in enumerate(ipos):
            md = f"{ipo['date'].month}/{ipo['date'].day}"
            mkt = f"[{ipo['market']}]" if ipo['market'] else ""
            name = ipo['name'][:max_name]
            price_str = f" 公募{ipo['price']}" if ipo['price'] else ""
            lines.append(f"{CIRCLED[i]}{name} {md}{mkt}{price_str}")

    if news:
        lines.append("")
        lines.append("📰 最新ニュース")
        for n in news:
            lines.append(n)

    lines.append("")
    lines.append("📱つむまね（無料）")
    lines.append(APP_URL)
    lines.append("#IPO #新規上場 #初値 #つむまね")
    return "\n".join(lines)


def format_tweet(ipos: list, news: list) -> str:
    """280文字に収まるまで銘柄名を段階的に短縮"""
    for max_name in range(10, 2, -1):
        tweet = build_tweet(ipos, news, max_name)
        if tw_len(tweet) <= MAX_CHARS:
            return tweet
    return build_tweet(ipos, news, 3)


# ── メイン ─────────────────────────────────────────────────────
def main():
    print("📋 IPO情報取得中...")
    ipos = get_ipo_schedule()
    news = get_ipo_news()

    print(f"  スケジュール: {len(ipos)}件")
    for ipo in ipos:
        print(f"    - {ipo['name']} ({ipo['date']}) [{ipo['market']}]")
    print(f"  ニュース: {len(news)}件")
    for n in news:
        print(f"    - {n}")

    if not ipos and not news:
        print("❌ データなし - スキップします")
        return

    tweet = format_tweet(ipos, news)
    print(f"\n投稿内容({tw_len(tweet)}文字):\n{tweet}\n")

    try:
        response = client.create_tweet(text=tweet)
        print(f"✅ IPOツイート成功: ID={response.data['id']}")
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
