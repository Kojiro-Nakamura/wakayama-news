import os
import re
import json
import time
import shutil
import urllib.parse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Tuple, Any

from difflib import SequenceMatcher
import feedparser
import requests
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
DATA_DIR = os.path.join(DOCS_DIR, "data")
DATES_DIR = os.path.join(DATA_DIR, "dates")

WAKAYAMA_KEYWORDS = [
    "和歌山", "紀州", "白浜", "高野山", "熊野", "田辺", "新宮", "有田", 
    "御坊", "橋本", "海南", "岩出", "紀の川", "串本", "那智勝浦", "九度山", 
    "かつらぎ", "湯浅", "広川", "みなべ", "日高", "印南", "由良", "美浜", 
    "日高川", "すさみ", "古座川", "太地", "北山", "紀美野", "アドベンチャーワールド",
    "南紀", "紀南", "紀北", "紀中"
]

def is_wakayama_relevant(title: str, text: str) -> bool:
    combined = title + " " + text
    return any(kw in combined for kw in WAKAYAMA_KEYWORDS)

def decode_google_news_url(google_rss_url: str) -> str:
    try:
        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
        }
        resp = requests.get(google_rss_url, headers=headers, timeout=6)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')
        container = soup.select_one('c-wiz[data-p]')
        if not container:
            return google_rss_url
        
        data_p = container.get('data-p')
        obj = json.loads(data_p.replace('%.@.', '["garturlreq",'))

        payload = {
            'f.req': json.dumps([[
                ['Fbv4je', json.dumps(obj[:-6] + obj[-2:]), 'null', 'generic']
            ]])
        }
        
        api_url = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
        api_headers = {
            'content-type': 'application/x-www-form-urlencoded;charset=UTF-8',
            'user-agent': headers['user-agent']
        }

        response = requests.post(api_url, headers=api_headers, data=payload, timeout=6)
        response.raise_for_status()

        raw_text = response.text.replace(")]}'", "")
        response_json = json.loads(raw_text)
        
        array_string = response_json[0][2]
        article_url = json.loads(array_string)[1]
        return article_url
    except Exception:
        return google_rss_url

def is_garbled_text(text: str) -> bool:
    """UTF-8バイト列がISO-8859-1等で誤読されたような文字化け（æ, ã, é等の連続、日本語の欠如）を検知"""
    if not text:
        return False
    jp_chars = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fa5]', text))
    mojibake_chars = len(re.findall(r'[æøåãðþïéèàù§©®]', text))
    if mojibake_chars >= 2 and jp_chars < 5:
        return True
    return False

def clean_for_dedup(s: str) -> str:
    """文の重複・類似比較用に記号・空白を除去"""
    return re.sub(r'[\s\u3000「」『』【】（）()・…、。！？!?\-\|:：]', '', s).lower()

def fetch_article_content(url: str) -> Tuple[str, str]:
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=6)
        resp.raise_for_status()

        # requestsのISO-8859-1誤認による文字化けを防止
        if not resp.encoding or resp.encoding.lower() in ('iso-8859-1', 'latin1', 'us-ascii'):
            resp.encoding = resp.apparent_encoding or 'utf-8'

        soup = BeautifulSoup(resp.text, 'html.parser')
        
        meta_desc = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'})
        desc = meta_desc['content'].strip() if meta_desc and meta_desc.get('content') else ''
        # 末尾が … や ... で途切れている不完全なディスクリプションは破棄して本文を優先
        if desc.endswith('…') or desc.endswith('...') or len(desc) < 30 or is_garbled_text(desc):
            desc = ''
        
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript']):
            tag.decompose()

        bad_words = [
            'JavaScript', 'クッキー', 'Cookie', '利用規約', '無断転載', '禁無断転載',
            '有料会員', 'ログイン', '本文へスキップ', '閲覧支援', '文字サイズ', 'サイトマップ',
            'サイト内検索', 'プライバシーポリシー', 'お問い合わせ', 'ページ先頭', '報道発表日', '更新日',
            '本プレスリリースの内容は', 'プレスリリース一覧', '電話', 'TEL', 'FAX', 'メールアドレス',
            'アンケート', '質問1', '質問2', 'お問合せ先', 'お問い合わせ先', '外部リンク', '再生ボタン', '担当者名', '係'
        ]

        main_container = soup.find(['article', 'main']) or soup.find(id=re.compile(r'content|main|article', re.I)) or soup.find(class_=re.compile(r'entry|content|main|article', re.I)) or soup
            
        paragraphs = []
        raw_lines = [line.strip() for line in main_container.get_text().splitlines() if len(line.strip()) > 15]
        for line in raw_lines:
            if any(bad in line for bad in bad_words) or is_garbled_text(line):
                continue
            line_norm = clean_for_dedup(line)
            if not any(SequenceMatcher(None, clean_for_dedup(p), line_norm).ratio() > 0.65 for p in paragraphs):
                paragraphs.append(line)
            if len(paragraphs) >= 8:
                break
                
        body_text = "\n".join(paragraphs[:6])
        return desc, body_text
    except Exception:
        return "", ""

def classify_category(title: str, text: str) -> str:
    combined = (title + " " + text).lower()
    categories = [
        ("観光・文化", ["観光", "世界遺産", "高野山", "熊野", "熊野古道", "白浜", "パンダ", "アドベンチャーワールド", "温泉", "祭り", "寺", "神社", "博物館", "那智", "太地"]),
        ("社会・事件", ["事故", "火災", "警察", "逮捕", "容疑", "遭難", "救助", "裁判", "捜査", "盗難", "死亡", "負傷", "転倒", "交通", "被害"]),
        ("政治・行政", ["知事", "県政", "県議会", "市議会", "市長", "町長", "和歌山市", "庁舎", "選挙", "予算", "条例", "政策", "補助金", "公約"]),
        ("スポーツ", ["野球", "サッカー", "国スポ", "アルテリーヴォ", "高校野球", "国体", "大会", "陸上", "優勝", "選手", "バスケ", "勝利", "プロ野球"]),
        ("経済・産業", ["企業", "新商品", "オープン", "開店", "特産", "みかん", "梅干し", "有田みかん", "紀州", "漁業", "農業", "商工", "開発", "物産", "就職", "振興"])
    ]
    for cat_name, keywords in categories:
        for kw in keywords:
            if kw.lower() in combined:
                return cat_name
    return "地域・一般"

def generate_summary_with_gemini(title: str, body: str, api_key: str) -> Optional[str]:
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = f"""以下の和歌山県に関するニュース記事を、読者が30秒で理解できるように「3つの要点」に要約してください。
必ず以下のフォーマットで出力してください。挨拶や前置き、解説は一切不要です。

【タイトル】{title}
【内容】{body}

出力形式：
・（要点1：50字以内）
・（要点2：50字以内）
・（要点3：50字以内）"""

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        print(f"Gemini API Error: {e}")
    return None

def create_auto_summary(title: str, desc: str, body: str) -> str:
    """自動要約生成（重複文・タイトル重複を徹底排除）"""
    base_text = (desc + "\n" + body).strip() if (desc and body) else (desc if desc else body)
    if not base_text or is_garbled_text(base_text):
        return f"・{title}"
    clean = re.sub(r'【写真を見る】.*', '', base_text)
    clean = re.sub(r'（.*放送）', '', clean)
    clean = re.sub(r'https?://\S+', '', clean)
    clean = clean.strip()

    title_norm = clean_for_dedup(title)
    raw_sentences = [s.strip() for s in re.split(r'。|\n', clean) if len(s.strip()) > 10 and not is_garbled_text(s)]

    unique_sentences: List[str] = []
    for s in raw_sentences:
        # 末尾が … や ... で切れている不完全な文はスキップ
        if s.endswith('…') or s.endswith('...') or s.endswith('..'):
            continue
        s_norm = clean_for_dedup(s)
        if len(s_norm) < 10:
            continue
        # タイトルと類似（70%以上一致、またはタイトルの包含）する文をスキップ
        if SequenceMatcher(None, title_norm, s_norm).ratio() > 0.70:
            continue
        if s_norm in title_norm or (len(s_norm) < 60 and title_norm in s_norm):
            continue
        # 既に選んだ要約文と類似（60%以上一致）する文をスキップ
        if any(SequenceMatcher(None, clean_for_dedup(u), s_norm).ratio() > 0.60 for u in unique_sentences):
            continue
        unique_sentences.append(s)
        if len(unique_sentences) >= 3:
            break

    def finish_sentence(text: str) -> str:
        t = text.strip()
        if not t.endswith(('。', '！', '!', '？', '?')):
            return t + '。'
        return t

    if len(unique_sentences) >= 2:
        return "\n".join(f"・{finish_sentence(s)}" for s in unique_sentences[:3])
    elif len(unique_sentences) == 1:
        return f"・{finish_sentence(unique_sentences[0])}"
    else:
        return f"・{title}"

def process_single_entry(entry: Any, gemini_key: str) -> Optional[Dict[str, Any]]:
    google_url = entry.get('link', '')
    if not google_url:
        return None
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        dt_utc = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        dt_jst = dt_utc.astimezone(JST)
        article_date = dt_jst.strftime('%Y-%m-%d')
        published_str = dt_jst.strftime('%Y-%m-%d %H:%M')
    else:
        now_jst = datetime.now(JST)
        article_date = now_jst.strftime('%Y-%m-%d')
        published_str = now_jst.strftime('%Y-%m-%d %H:%M')
        
    raw_title = entry.get('title', '').strip()
    source = entry.get('source', {}).get('title', 'ニュース配信元')
    clean_title = re.sub(r' - [^-]+$', '', raw_title)
    
    real_url = decode_google_news_url(google_url)
    desc, body = fetch_article_content(real_url)
    
    if not is_wakayama_relevant(clean_title, desc + " " + body):
        return None
        
    category = classify_category(clean_title, desc + " " + body)
    
    summary_type = 'auto'
    summary_text = ""
    if gemini_key:
        ai_sum = generate_summary_with_gemini(clean_title, desc + "\n" + body, gemini_key)
        if ai_sum:
            summary_text = ai_sum
            summary_type = 'ai'
            
    if not summary_text:
        summary_text = create_auto_summary(clean_title, desc, body)
        summary_type = 'auto'
        
    return {
        "article_date": article_date,
        "title": clean_title,
        "url": real_url,
        "source": source,
        "published_at": published_str,
        "summary": summary_text,
        "summary_type": summary_type,
        "category": category
    }

def clean_title_for_clustering(title: str) -> str:
    """タイトルの記号やメディア表記を除去して比較用文字列を作成"""
    t = re.sub(r'[\(（【\[].*?[\)）】\]]', '', title)
    t = re.sub(r'\s*-\s*[^-]+$', '', t)
    t = re.sub(r'\s*\|\s*[^|]+$', '', t)
    t = re.sub(r'[「」『』【】（）()・…、。！？!?\s]', '', t)
    return t

def extract_title_keywords(title: str) -> set:
    """タイトルから2文字以上の重要キーワードを抽出"""
    words = set(re.findall(r'[\u4e00-\u9fa5]{2,}|[\u30a1-\u30f6]{2,}|[A-Za-z0-9]{2,}', title))
    stopwords = {"ニュース", "詳細", "放送", "速報", "今日", "昨日", "和歌山", "和歌山県", "全国", "日本"}
    return words - stopwords

def are_articles_same_topic(a1: dict, a2: dict) -> bool:
    """2つの記事が同一の出来事・トピックを報じているか判定"""
    t1 = clean_title_for_clustering(a1.get('title', ''))
    t2 = clean_title_for_clustering(a2.get('title', ''))
    
    # 完全一致または内包
    if t1 and t2 and (t1 in t2 or t2 in t1):
        return True
        
    # 文字列類似度（SequenceMatcher）
    ratio = SequenceMatcher(None, t1, t2).ratio()
    if ratio >= 0.52:
        return True
        
    # キーワード重複判定
    kw1 = extract_title_keywords(a1.get('title', ''))
    kw2 = extract_title_keywords(a2.get('title', ''))
    common = kw1 & kw2
    if len(common) >= 3:
        return True
        
    # 地震などの速報
    if ("地震" in t1 or "震度" in t1) and ("地震" in t2 or "震度" in t2):
        if len(common & {"震度2", "震度1", "震度3", "紀伊水道", "最大震度", "湯浅町", "小松島市", "徳島県"}) >= 1:
            return True
            
    return False

def cluster_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同じトピックの記事を1つの代表記事にまとめ、他を related_articles に格納"""
    clusters: List[Dict[str, Any]] = []
    for item in articles:
        # すでに別記事の related_articles に入っているものは展開
        existing_related = item.pop("related_articles", [])
        candidates = [item] + existing_related
        
        for cand in candidates:
            matched = False
            for group in clusters:
                if are_articles_same_topic(group, cand):
                    urls = {group.get("url")} | {r.get("url") for r in group.get("related_articles", [])}
                    if cand.get("url") not in urls:
                        group.setdefault("related_articles", []).append({
                            "title": cand.get("title"),
                            "url": cand.get("url"),
                            "source": cand.get("source"),
                            "published_at": cand.get("published_at")
                        })
                    matched = True
                    break
            if not matched:
                cand["related_articles"] = []
                clusters.append(cand)
                
    return clusters

def import_sqlite_data():
    """既存のSQLiteデータがあれば読み込む"""
    sqlite_path = os.path.join(BASE_DIR, "data", "wakayama_news.db")
    if not os.path.exists(sqlite_path):
        return {}
    import sqlite3
    articles_by_date = {}
    try:
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM articles")
        rows = cursor.fetchall()
        for r in rows:
            d = r["article_date"]
            if d not in articles_by_date:
                articles_by_date[d] = []
            articles_by_date[d].append({
                "article_date": r["article_date"],
                "title": r["title"],
                "url": r["url"],
                "source": r["source"],
                "published_at": r["published_at"],
                "summary": r["summary"],
                "summary_type": r["summary_type"],
                "category": r["category"]
            })
        conn.close()
    except Exception as e:
        print(f"SQLite import warning: {e}")
    return articles_by_date

def build_static_site():
    print("=== 和歌山デイリーニュース 静的サイト＆データ構築開始 ===")
    os.makedirs(DATES_DIR, exist_ok=True)
    
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    
    # 既存のJSONアーカイブを読み込み
    articles_by_date = import_sqlite_data()
    
    # 既存のdocs/data/dates/*.jsonがあればそれもロード
    for fn in os.listdir(DATES_DIR):
        if fn.endswith(".json"):
            date_str = fn.replace(".json", "")
            fpath = os.path.join(DATES_DIR, fn)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                    if date_str not in articles_by_date:
                        articles_by_date[date_str] = []
                    # URLでユニーク判定
                    seen_urls = {a["url"] for a in articles_by_date[date_str]}
                    for item in existing:
                        if item["url"] not in seen_urls:
                            articles_by_date[date_str].append(item)
                            seen_urls.add(item["url"])
            except Exception as e:
                print(f"Error loading {fn}: {e}")

    # Google Newsから最新ニュースを取得
    queries = ["和歌山県", "和歌山市"]
    seen_links = set()
    raw_entries = []
    
    for q in queries:
        encoded = urllib.parse.quote(q)
        rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=ja&gl=JP&ceid=JP:ja"
        feed = feedparser.parse(rss_url)
        for e in feed.entries[:25]:
            link = e.get('link')
            if link and link not in seen_links:
                seen_links.add(link)
                raw_entries.append(e)

    print(f"Google Newsから {len(raw_entries)} 件の候補を取得。並列処理中...")
    
    new_articles = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(process_single_entry, entry, gemini_key) for entry in raw_entries]
        for f in as_completed(futures):
            try:
                res = f.result()
                if res:
                    new_articles.append(res)
            except Exception as ex:
                print(f"Entry error: {ex}")

    # 日付ごとにマージ
    new_added_count = 0
    for a in new_articles:
        d = a["article_date"]
        if d not in articles_by_date:
            articles_by_date[d] = []
        # URL重複チェック
        existing_urls = {item["url"] for item in articles_by_date[d]}
        if a["url"] not in existing_urls:
            articles_by_date[d].append(a)
            new_added_count += 1

    print(f"新着追加記事数: {new_added_count} 件")

    # 各日付のJSONファイルを保存（新しい記事順にソート）
    date_list = []
    total_articles = 0
    all_articles_index = []

    for d in sorted(articles_by_date.keys(), reverse=True):
        raw_items = articles_by_date[d]
        raw_items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
        # 同一トピックの記事をグルーピング
        items = cluster_articles(raw_items)
        
        date_file = os.path.join(DATES_DIR, f"{d}.json")
        with open(date_file, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
            
        # 記事総数（関連報道含む）
        day_total = sum(1 + len(x.get("related_articles", [])) for x in items)
        total_articles += day_total
        date_list.append({
            "article_date": d,
            "count": len(items) # 表示されるトピック数
        })
        
        # 検索用インデックス
        for item in items:
            if len(all_articles_index) < 150:
                all_articles_index.append(item)

    # index.json を保存
    index_data = {
        "dates": date_list,
        "stats": {
            "total_articles": total_articles,
            "total_days": len(date_list),
            "last_updated": datetime.now(JST).isoformat()
        }
    }
    with open(os.path.join(DATA_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)

    with open(os.path.join(DATA_DIR, "search_index.json"), "w", encoding="utf-8") as f:
        json.dump(all_articles_index, f, ensure_ascii=False, indent=2)

    print(f"=== 構築完了: 全 {total_articles} 件、{len(date_list)} 日分のアーカイブを生成 ===")

if __name__ == "__main__":
    build_static_site()
