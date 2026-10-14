import os
import re
import json
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import feedparser
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Tuple, Any

import database

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

# 和歌山県全30市町村および6郡、地域キーワード
WAKAYAMA_MUNICIPALITIES = [
    # 9市
    "和歌山市", "海南市", "橋本市", "有田市", "御坊市", "田辺市", "新宮市", "紀の川市", "岩出市",
    # 6郡
    "海草郡", "伊都郡", "有田郡", "日高郡", "西牟婁郡", "東牟婁郡",
    # 20町・1村
    "紀美野町", "かつらぎ町", "九度山町", "高野町", "湯浅町", "広川町", "有田川町",
    "美浜町", "日高町", "由良町", "印南町", "みなべ町", "日高川町",
    "白浜町", "上富田町", "すさみ町", "那智勝浦町", "太地町", "古座川町", "北山村", "串本町"
]

WAKAYAMA_KEYWORDS = WAKAYAMA_MUNICIPALITIES + [
    # 短縮表記・主要地名・地域名
    "和歌山", "紀州", "白浜", "高野山", "熊野", "熊野古道", "有田川", "上富田",
    "すさみ", "古座川", "太地", "北山", "紀美野", "アドベンチャーワールド",
    "南紀", "紀南", "紀北", "紀中", "潮岬", "那智の滝", "貴志川線", "たま駅長",
    "かつらぎ", "九度山", "湯浅", "広川", "みなべ", "印南", "由良", "日高川",
    "那智勝浦", "串本", "田辺", "新宮", "有田", "御坊", "橋本", "海南", "岩出", "紀の川"
]

# 他県と同名になりやすい町村名（愛知・福井・北海道・福岡等の誤爆防止フィルター用）
AMBIGUOUS_TOWN_KEYWORDS = {
    "美浜町": ["愛知", "知多郡", "福井", "三方郡", "千葉", "美浜区"],
    "美浜": ["愛知", "知多郡", "福井", "三方郡", "千葉", "美浜区"],
    "日高町": ["北海道", "沙流郡", "豊岡"],
    "日高": ["北海道", "沙流郡", "日高山脈", "日高振興局", "豊岡"],
    "広川町": ["福岡", "八女郡"],
    "広川": ["福岡", "八女郡"],
    "新宮市": ["福岡", "糟屋郡", "新宮町"],
    "北山": ["京都", "北山区"]
}

# 確実に和歌山県内と判定できるアンカーキーワード
STRONG_WAKAYAMA_ANCHORS = [
    "和歌山", "和歌山県", "紀州", "紀南", "紀北", "紀中", "南紀", "高野山", "熊野", "熊野古道",
    "白浜町", "アドベンチャーワールド", "和歌山市", "海南市", "橋本市", "有田市", "御坊市", "田辺市", "紀の川市", "岩出市",
    "海草郡", "伊都郡", "有田郡", "日高郡", "西牟婁郡", "東牟婁郡"
]

def is_wakayama_relevant(title: str, text: str) -> bool:
    """和歌山関連のニュースであるかを厳密に判定"""
    combined = title + " " + text
    
    # 強い和歌山キーワードが含まれていれば即OK
    if any(anchor in combined for anchor in STRONG_WAKAYAMA_ANCHORS):
        return True
        
    # いずれかの和歌山キーワードに合致するか
    matched_kws = [kw for kw in WAKAYAMA_KEYWORDS if kw in combined]
    if not matched_kws:
        return False
        
    # 曖昧な地名のみで合致した場合、他県の兆候があれば除外
    for kw in matched_kws:
        if kw in AMBIGUOUS_TOWN_KEYWORDS:
            other_clues = AMBIGUOUS_TOWN_KEYWORDS[kw]
            if any(clue in combined for clue in other_clues):
                # 他県の手がかりがあり、かつ強い和歌山キーワードがない場合は除外
                return False

    return True

def decode_google_news_url(google_rss_url: str) -> str:
    """Google News RSSの暗号化URLから実際の記事URLを復元"""
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

def fetch_article_content(url: str) -> Tuple[str, str]:
    """元記事のメタディスクリプションと本文テキストを取得"""
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=6)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        meta_desc = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'})
        desc = meta_desc['content'].strip() if meta_desc and meta_desc.get('content') else ''
        
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            tag.decompose()
            
        paragraphs = []
        for p in soup.find_all(['p', 'div']):
            text = p.get_text().strip()
            if len(text) > 25 and not any(bad in text for bad in ['JavaScript', 'クッキー', 'Cookie', '利用規約', '無断転載', '禁無断転載', '有料会員', 'ログイン']):
                if text not in paragraphs:
                    paragraphs.append(text)
            if len(paragraphs) >= 5:
                break
                
        body_text = "\n".join(paragraphs[:3])
        return desc, body_text
    except Exception:
        return "", ""

def classify_category(title: str, text: str) -> str:
    """ニュースのタイトルと本文からカテゴリを判定"""
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
    """Gemini APIを使用して3行箇条書き要約を生成"""
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
    """API不要の自動要約（メタディスクリプションやリード文を整形）"""
    base_text = desc if desc else body
    if not base_text:
        return f"・{title}"
        
    clean = re.sub(r'【写真を見る】.*', '', base_text)
    clean = re.sub(r'（.*放送）', '', clean)
    clean = re.sub(r'https?://\S+', '', clean)
    clean = clean.strip()
    
    sentences = [s.strip() for s in re.split(r'。|\n', clean) if len(s.strip()) > 10]
    
    if len(sentences) >= 2:
        points = [f"・{s}。" for s in sentences[:3]]
        return "\n".join(points)
    elif sentences:
        return f"・{sentences[0]}。"
    else:
        return f"・{clean[:120]}…"

def process_single_entry(entry: Any, gemini_key: str) -> Optional[Dict[str, Any]]:
    """1つのRSSエントリを処理して記事データを構築"""
    google_url = entry.get('link', '')
    if not google_url:
        return None
        
    # 日時
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
    
    # 元記事URLの復元
    real_url = decode_google_news_url(google_url)
    
    # 本文と説明文を取得
    desc, body = fetch_article_content(real_url)
    
    # 和歌山関連チェック
    if not is_wakayama_relevant(clean_title, desc + " " + body):
        return None
        
    # カテゴリ判定
    category = classify_category(clean_title, desc + " " + body)
    
    # 要約生成
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
        "google_url": google_url,
        "source": source,
        "published_at": published_str,
        "summary": summary_text,
        "summary_type": summary_type,
        "category": category
    }

def collect_news(max_items: int = 25) -> Dict[str, Any]:
    """Google News RSSから和歌山ニュースを並列取得してDBに保存"""
    database.init_db()
    gemini_key = database.get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    
    # 和歌山県全30市町村・6郡を網羅するGoogle News収集クエリ
    queries = [
        "和歌山県",
        "和歌山市",
        "海南市 OR 橋本市 OR 有田市 OR 御坊市 OR 紀の川市 OR 岩出市",
        "田辺市 OR 新宮市 OR 白浜町 OR 串本町 OR 那智勝浦町",
        "紀美野町 OR かつらぎ町 OR 九度山町 OR 高野町 OR 湯浅町 OR 有田川町",
        "由良町 OR 印南町 OR みなべ町 OR 日高川町",
        "上富田町 OR すさみ町 OR 太地町 OR 古座川町 OR 北山村",
        "和歌山 美浜町 OR 和歌山 日高町 OR 和歌山 広川町",
        "海草郡 OR 伊都郡 OR 有田郡 OR 日高郡 OR 西牟婁郡 OR 東牟婁郡",
        "紀州 OR 南紀 OR 紀南 OR 高野山 OR 熊野古道"
    ]
    seen_links = set()
    raw_entries = []
    
    for query in queries:
        encoded = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=ja&gl=JP&ceid=JP:ja"
        feed = feedparser.parse(rss_url)
        for e in feed.entries[:max_items]:
            link = e.get('link')
            if link and link not in seen_links:
                seen_links.add(link)
                raw_entries.append(e)
                
    new_articles_count = 0
    # スレッドプールで並列取得（高速化）
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(process_single_entry, entry, gemini_key) for entry in raw_entries]
        for f in as_completed(futures):
            try:
                res = f.result()
                if res:
                    inserted = database.insert_article(
                        article_date=res["article_date"],
                        title=res["title"],
                        url=res["url"],
                        google_url=res["google_url"],
                        source=res["source"],
                        published_at=res["published_at"],
                        summary=res["summary"],
                        summary_type=res["summary_type"],
                        category=res["category"]
                    )
                    if inserted:
                        new_articles_count += 1
            except Exception as ex:
                print(f"Error processing entry: {ex}")
                
    return {
        "status": "success",
        "new_articles": new_articles_count,
        "total_checked": len(raw_entries),
        "timestamp": datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
    }

if __name__ == "__main__":
    print("和歌山ニュース高速収集開始...")
    start_t = time.time()
    res = collect_news(max_items=15)
    print(f"完了 ({time.time() - start_t:.2f}秒):", res)
