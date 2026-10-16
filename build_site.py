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

def is_noise_text(line: str) -> bool:
    """日付のみ、会員誘導、おすすめ記事、広告キャンペーンなどのノイズ文を徹底判定"""
    l = line.strip()
    if len(l) < 8:
        return True
    # 日時・日付・時刻のみの行
    # 日時・日付・時刻のみの行、または日付時刻で終わる行
    if re.match(r'^(?:\d{4}[年/\-\.]\s*)?\d{1,2}[月/\-\.]\s*\d{1,2}日?\s*(?:\(?[\w曜]+\)?)?\s*(?:\d{1,2}:\d{2}(?::\d{2})?)?$', l):
        return True
    if re.match(r'^\d{1,2}:\d{2}(?::\d{2})?$', l):
        return True
    if re.search(r'\d{1,2}/\d{1,2}\s*(?:\([^\)]+\))?\s*\d{1,2}:\d{2}', l) and len(l) < 30:
        return True
    # 有料・会員・購読案内
    if any(k in l for k in [
        '会員限定', '有料会員', '有料コンテンツ', '読み放題', '初月無料', '月額', '税込',
        '残り', '全文', 'ログイン', '無料体験', 'お申し込み', '購読', '会員登録', '有料プラン'
    ]):
        return True
    # 広告・レコメンド・ランキング・キャンペーン
    if any(k in l for k in [
        'あなたにおすすめ', 'おすすめ記事', 'おすすめ情報', '関連記事', '他の記事', 'アクセスランキング', '最新ニュース',
        'ニュース一覧', '一覧へ', 'もっと見る', '円引き', '割引き', 'プレゼント', '抽選', '懸賞',
        'クーポン', 'キャンペーン', 'タイアップ', 'PR記事'
    ]):
        return True
    # システム・規約・UI
    if any(k in l for k in [
        'JavaScript', 'Cookie', 'クッキー', '利用規約', '無断転載', '禁無断転載',
        'プライバシーポリシー', 'お問い合わせ', 'サイトマップ', 'シェア', 'ツイート',
        'LINEで送る', 'ブックマーク', 'フォトギャラリー', '写真を見る', '再生ボタン'
    ]):
        return True
    return False

def is_incomplete_sentence(s: str) -> bool:
    """助詞や読点で途切れている不完全な文（例: '警察や' '対策を' 等）を検知"""
    t = s.strip().rstrip('。！？!?')
    if not t:
        return True
    if t.endswith(('…', '...', '..', '、', '，', '・', '「', '『', '（', '(')):
        return True
    # 末尾が助詞・接続表現で突然終わっている場合
    if re.search(r'(?:から|など|ため|ほか|ついて|よると|対し|向け|伴い|おける|として|による|および|または|ともに|ついては|関して|[やとのをにへでがはも])$', t):
        # ただし「〜だ」「〜た」「〜る」「〜い」「〜す」「〜ん」等の通常の文末は除外しない（上の正規表現は助詞のみ）
        # 「〜には」「〜では」等も引っかかるので確実に不完全
        return True
    return False

def rescue_meta_desc(raw_desc: str) -> str:
    """末尾が…で切れているメタディスクリプションから、完全な文（「。」で終わる文）を救出"""
    if not raw_desc or is_garbled_text(raw_desc):
        return ''
    raw_desc = raw_desc.strip()
    # 句点「。」で分割して完全な文だけを検証・救出
    parts = re.split(r'。', raw_desc)
    valid_parts = []
    for idx, p in enumerate(parts):
        p = p.strip()
        if not p or p.endswith(('…', '...', '..')):
            continue
        # 最後のパーツで、元テキストが句点で終わっていない場合は切れている可能性が高い
        if idx == len(parts) - 1 and not raw_desc.endswith(('。', '！', '!', '？', '?')):
            continue
        if len(p) >= 15 and not is_noise_text(p) and not is_garbled_text(p) and not is_incomplete_sentence(p):
            valid_parts.append(p + '。')
    if valid_parts:
        return ''.join(valid_parts)
    return ''

def extract_meaningful_tokens(text: str) -> set:
    """漢字熟語（2文字以上）、カタカナ語（3文字以上）、英単語（3文字以上）を意味のある語彙として抽出"""
    kanji = re.findall(r'[\u4e00-\u9fa5]{2,}', text)
    katakana = re.findall(r'[\u30a0-\u30ff]{3,}', text)
    alpha = re.findall(r'[a-zA-Z]{3,}', text)
    tokens = set(katakana + alpha)
    for k in kanji:
        tokens.add(k)
        for i in range(len(k) - 1):
            tokens.add(k[i:i+2])
    return tokens

def is_relevant_to_title(title: str, sentence: str) -> bool:
    """文がタイトルと文脈上の関連（実質的な語彙・熟語の一致）を持つか検証し、無関係な別記事や広告を完全排除"""
    t_tokens = extract_meaningful_tokens(title)
    if not t_tokens:
        return True
    s_tokens = extract_meaningful_tokens(sentence)
    common = t_tokens.intersection(s_tokens)
    return len(common) >= 1

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
        raw_desc = meta_desc['content'].strip() if meta_desc and meta_desc.get('content') else ''
        desc = rescue_meta_desc(raw_desc)
        
        # 不要なタグ・セクションの徹底分解・削除
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript', 'form', 'figure', 'figcaption']):
            tag.decompose()

        # 広告・レコメンド・ランキング・会員限定誘導・サイドバーのコンテナを全削除
        noise_pattern = re.compile(
            r'(recommend|related|ranking|paywall|member|subscription|banner|ad-|sidebar|sns|social|comment|breadcrumb|share|pickup|popular|follow|entry-date|post-date|campaign)',
            re.I
        )
        for tag in soup.find_all(attrs={'class': noise_pattern}):
            tag.decompose()
        for tag in soup.find_all(attrs={'id': noise_pattern}):
            tag.decompose()

        body_soup = soup.body or soup

        # 本文コンテナの特定（記事本文らしい専用クラスを最優先）
        main_container = None
        for candidate in [
            body_soup.select_one('div.limited_main_text'),
            body_soup.select_one('div.news_item'),
            body_soup.find(['article', 'main']),
            body_soup.find(['div', 'section'], class_=re.compile(r'^(?!.*(css|js|style|grid)).*(entry-content|article-body|main-text|post-content|story-body)', re.I)),
            body_soup.find(['div', 'section'], id=re.compile(r'^(?!.*(css|js|style|grid)).*(entry-content|article-body|main-text|post-content)', re.I)),
            body_soup
        ]:
            if candidate and len(candidate.get_text().strip()) > 60:
                main_container = candidate
                break

        if not main_container:
            main_container = body_soup
            
        paragraphs = []
        for p in main_container.find_all('p'):
            text = p.get_text().strip()
            if len(text) > 20 and not is_noise_text(text) and not is_garbled_text(text):
                if text not in paragraphs:
                    paragraphs.append(text)
            if len(paragraphs) >= 8:
                break

        if len(paragraphs) < 3:
            raw_lines = [line.strip() for line in main_container.get_text().splitlines() if len(line.strip()) > 15]
            for line in raw_lines:
                if is_noise_text(line) or is_garbled_text(line):
                    continue
                line_norm = clean_for_dedup(line)
                if not any(SequenceMatcher(None, clean_for_dedup(p), line_norm).ratio() > 0.65 for p in paragraphs):
                    paragraphs.append(line)
                if len(paragraphs) >= 10:
                    break
                
        body_text = "\n".join(paragraphs[:8])
        return desc, body_text
    except Exception:
        return "", ""

def classify_category(title: str, text: str) -> str:
    combined = (title + " " + text).lower()
    categories = [
        ("観光・文化", ["観光", "世界遺産", "高野山", "熊野", "熊野古道", "白浜", "パンダ", "アドベンチャーワールド", "温泉", "祭り", "寺", "神社", "博物館", "那智", "太地", "串本", "潮岬", "文化財", "体験"]),
        ("社会・事件", ["事故", "火災", "警察", "逮捕", "容疑", "遭難", "救助", "裁判", "捜査", "盗難", "死亡", "負傷", "転倒", "交通", "被害", "クマ", "訓練", "防災", "詐欺"]),
        ("政治・行政", ["知事", "県政", "県議会", "市議会", "町議会", "市長", "町長", "村長", "和歌山市", "庁舎", "役場", "選挙", "予算", "条例", "政策", "補助金", "公約", "県庁"]),
        ("スポーツ", ["野球", "サッカー", "国スポ", "アルテリーヴォ", "高校野球", "国体", "大会", "陸上", "優勝", "選手", "バスケ", "バレー", "勝利", "プロ野球", "マラソン"]),
        ("経済・産業", ["企業", "新商品", "オープン", "開店", "特産", "みかん", "梅干し", "南高梅", "有田みかん", "紀州", "漁業", "農業", "商工", "開発", "物産", "就職", "振興", "販売"])
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

def score_sentence_importance(title: str, sentence: str, index: int) -> float:
    """文の重要度スコアを算出（キーワード密度・数値ファクト・結論表現・位置ボーナス）"""
    score = 0.0
    t_tokens = extract_meaningful_tokens(title)
    s_tokens = extract_meaningful_tokens(sentence)
    overlap = len(t_tokens.intersection(s_tokens))
    score += overlap * 3.0

    # 数値データ・日付・単位（5W1Hの具体性）
    facts = re.findall(r'\d+(?:年|月|日|時|分|人|名|件|円|万円|億円|%|％|歳|本|棟|km|m|ha|トン|t|倍|回|校|社|店|頭|匹)', sentence)
    score += min(len(facts) * 2.5, 7.5)

    # ニュースの核心アクション動詞
    if re.search(r'(?:発表|決定|開始|開催|判明|逮捕|完成|発売|開発|公開|策定|受賞|合意|オープン|開幕|設置|導入|再開|確認|贈呈|寄贈|寄付|選出|優勝|実施|開通)', sentence):
        score += 3.5

    # リード文（第1〜2文）ボーナス
    if index == 0:
        score += 4.0
    elif index == 1:
        score += 2.5
    elif index == 2:
        score += 1.0

    # 適切な文字数ボーナス
    if 25 <= len(sentence) <= 115:
        score += 2.0
    elif len(sentence) > 150:
        score -= 2.0

    # 挨拶・ブログ風定型文の減点
    if re.search(r'(?:こんにちは|こんばんは|おはようございます|いかがでしたか|ご紹介します|お伝えします|今回は|お天気サポート)', sentence):
        score -= 8.0

    return score

def create_auto_summary(title: str, desc: str, body: str) -> str:
    """重要度スコアリング搭載の自動要約エンジン（不完全文・重複・タイトル反復を徹底排除）"""
    # bodyを先に、descを補助にすることで途中で切れたdescよりも完全な本文段落を優先
    base_text = (body + "\n" + desc).strip() if (body and desc) else (body if body else desc)
    if not base_text or is_garbled_text(base_text):
        return f"・{title}"
    clean = re.sub(r'【写真を見る】.*', '', base_text)
    clean = re.sub(r'（.*放送）', '', clean)
    clean = re.sub(r'https?://\S+', '', clean)
    clean = clean.strip()

    title_norm = clean_for_dedup(title)
    raw_sentences = [s.strip() for s in re.split(r'。|\n', clean) if len(s.strip()) > 12 and not is_garbled_text(s)]

    candidates: List[Tuple[int, float, str]] = []
    accepted_norms: List[str] = []

    for idx, s in enumerate(raw_sentences):
        if is_noise_text(s):
            continue
        if is_incomplete_sentence(s):
            continue
        if not is_relevant_to_title(title, s):
            continue
        s_norm = clean_for_dedup(s)
        if len(s_norm) < 12:
            continue
        # タイトルと類似（70%以上一致、または包含）する文をスキップ
        if SequenceMatcher(None, title_norm, s_norm).ratio() > 0.70:
            continue
        if s_norm in title_norm or (len(s_norm) < 60 and title_norm in s_norm):
            continue
        # 既に候補に入れた文と類似（58%以上一致）する文をスキップ
        if any(SequenceMatcher(None, u_norm, s_norm).ratio() > 0.58 for u_norm in accepted_norms):
            continue

        sc = score_sentence_importance(title, s, idx)
        candidates.append((idx, sc, s))
        accepted_norms.append(s_norm)

    # スコア上位3文を選び、元の文章の登場順（idx順）に並べることで自然な文脈を維持
    top_candidates = sorted(candidates, key=lambda x: x[1], reverse=True)[:3]
    top_candidates.sort(key=lambda x: x[0])
    selected_sentences = [x[2] for x in top_candidates]

    def finish_sentence(text: str) -> str:
        t = text.strip()
        if not t.endswith(('。', '！', '!', '？', '?')):
            return t + '。'
        return t

    if len(selected_sentences) >= 2:
        return "\n".join(f"・{finish_sentence(s)}" for s in selected_sentences[:3])
    elif len(selected_sentences) == 1:
        return f"・{finish_sentence(selected_sentences[0])}"
    else:
        return f"・{title}"

def sanitize_existing_summary(title: str, summary: str) -> str:
    """既存データの要約に不完全な文（例: '警察や。'）が含まれていればクリーンアップ"""
    if not summary:
        return f"・{title}"
    lines = [l.strip() for l in summary.splitlines() if l.strip()]
    valid_lines = []
    for l in lines:
        core = l.lstrip('・• ').strip()
        if is_incomplete_sentence(core):
            continue
        valid_lines.append(f"・{core if core.endswith(('。', '！', '!', '？', '?')) else core + '。'}")
    if valid_lines:
        return "\n".join(valid_lines)
    return f"・{title}"

def process_article_item(real_url: str, title: str, source: str, article_date: str, published_str: str, gemini_key: str, require_relevance_check: bool = True) -> Optional[Dict[str, Any]]:
    """単一記事URLの本文取得・要約・カテゴリ分類を実行"""
    desc, body = fetch_article_content(real_url)
    
    if require_relevance_check and not is_wakayama_relevant(title, desc + " " + body):
        return None
        
    category = classify_category(title, desc + " " + body)
    
    summary_type = 'auto'
    summary_text = ""
    if gemini_key:
        ai_sum = generate_summary_with_gemini(title, desc + "\n" + body, gemini_key)
        if ai_sum:
            summary_text = ai_sum
            summary_type = 'ai'
            
    if not summary_text:
        summary_text = create_auto_summary(title, desc, body)
        summary_type = 'auto'
        
    return {
        "article_date": article_date,
        "title": title,
        "url": real_url,
        "source": source,
        "published_at": published_str,
        "summary": summary_text,
        "summary_type": summary_type,
        "category": category
    }

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
    return process_article_item(real_url, clean_title, source, article_date, published_str, gemini_key, require_relevance_check=True)

def fetch_agara_items() -> List[Dict[str, Any]]:
    """紀伊民報（AGARA: https://www.agara.co.jp/）から最新記事を取得"""
    url = "https://www.agara.co.jp/"
    headers = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    print(f"紀伊民報 (AGARA) から記事取得中: {url}")
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = r.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        items = []
        seen = set()
        now_str = datetime.now(JST).strftime('%Y-%m-%d')
        now_pub = datetime.now(JST).strftime('%Y-%m-%d %H:%M')
        for a in soup.find_all('a', href=re.compile(r'^/article/\d+')):
            href = "https://www.agara.co.jp" + a['href']
            if href in seen:
                continue
            title = re.sub(r'\s+', ' ', a.get_text()).strip()
            # 日付・時刻表記がタイトル末尾等に入っている場合は整形
            title = re.sub(r'\s*\d{4}年\d{1,2}月\d{1,2}日.*$', '', title).strip()
            if len(title) < 10 or 'あがらの日記' in title:
                continue
            seen.add(href)
            items.append({
                'title': title,
                'url': href,
                'source': '紀伊民報',
                'article_date': now_str,
                'published_at': now_pub
            })
            if len(items) >= 20:
                break
        print(f"紀伊民報 から {len(items)} 件を取得しました。")
        return items
    except Exception as e:
        print(f"AGARA fetch error: {e}")
        return []

def fetch_wbs_items() -> List[Dict[str, Any]]:
    """WBS和歌山放送ニュース（https://news.wbs.co.jp/）から最新記事を取得"""
    url = "https://news.wbs.co.jp/"
    headers = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    print(f"WBS和歌山放送ニュース から記事取得中: {url}")
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = r.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        items = []
        seen = set()
        now_str = datetime.now(JST).strftime('%Y-%m-%d')
        now_pub = datetime.now(JST).strftime('%Y-%m-%d %H:%M')
        for a in soup.find_all('a', href=re.compile(r'https://news\.wbs\.co\.jp/\d+')):
            href = a['href']
            if href in seen:
                continue
            title = re.sub(r'\s+', ' ', a.get_text()).strip()
            if len(title) < 8:
                continue
            seen.add(href)
            items.append({
                'title': title,
                'url': href,
                'source': 'WBS和歌山放送ニュース',
                'article_date': now_str,
                'published_at': now_pub
            })
            if len(items) >= 15:
                break
        print(f"WBS和歌山放送ニュース から {len(items)} 件を取得しました。")
        return items
    except Exception as e:
        print(f"WBS fetch error: {e}")
        return []

def fetch_wakayama_shimpo_items() -> List[Dict[str, Any]]:
    """わかやま新報（https://www.wakayamashimpo.co.jp/feed/）から最新記事を取得"""
    feed_url = "https://www.wakayamashimpo.co.jp/feed/"
    print(f"わかやま新報 からフィード取得中: {feed_url}")
    try:
        f = feedparser.parse(feed_url)
        items = []
        for e in f.entries[:15]:
            href = e.link
            title = e.title.strip()
            if hasattr(e, 'published_parsed') and e.published_parsed:
                dt_utc = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
                dt_jst = dt_utc.astimezone(JST)
                entry_date = dt_jst.strftime('%Y-%m-%d')
                pub_str = dt_jst.strftime('%Y-%m-%d %H:%M')
            else:
                entry_date = datetime.now(JST).strftime('%Y-%m-%d')
                pub_str = f"{entry_date} 09:00"
            items.append({
                'title': title,
                'url': href,
                'source': 'わかやま新報',
                'article_date': entry_date,
                'published_at': pub_str
            })
        print(f"わかやま新報 から {len(items)} 件を取得しました。")
        return items
    except Exception as e:
        print(f"Wakayama Shimpo fetch error: {e}")
        return []

def fetch_hidaka_shimpo_items() -> List[Dict[str, Any]]:
    """日高新報（https://hidakashimpo.co.jp/）から最新記事を取得"""
    url = "https://hidakashimpo.co.jp/"
    headers = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    print(f"日高新報 から記事取得中: {url}")
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = r.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        items = []
        seen = set()
        now_str = datetime.now(JST).strftime('%Y-%m-%d')
        now_pub = datetime.now(JST).strftime('%Y-%m-%d %H:%M')
        for a in soup.find_all('a', href=re.compile(r'https://hidakashimpo\.co\.jp/\?p=\d+')):
            href = a['href']
            if href in seen:
                continue
            title = re.sub(r'\s+', ' ', a.get_text()).strip()
            if len(title) < 8 or '続きを読む' in title:
                continue
            seen.add(href)
            items.append({
                'title': title,
                'url': href,
                'source': '日高新報',
                'article_date': now_str,
                'published_at': now_pub
            })
            if len(items) >= 15:
                break
        print(f"日高新報 から {len(items)} 件を取得しました。")
        return items
    except Exception as e:
        print(f"Hidaka Shimpo fetch error: {e}")
        return []

def fetch_wakayama_pref_items() -> List[Dict[str, Any]]:
    """和歌山県庁 県政ニュース（http://wave.pref.wakayama.lg.jp/news/kensei/）から報道発表を取得"""
    url = "http://wave.pref.wakayama.lg.jp/news/kensei/"
    headers = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    print(f"和歌山県庁 県政ニュース から取得中: {url}")
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = r.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        items = []
        seen = set()
        now_str = datetime.now(JST).strftime('%Y-%m-%d')
        now_pub = datetime.now(JST).strftime('%Y-%m-%d 10:00')
        for a in soup.find_all('a', href=re.compile(r'shiryo\.php\?sid=\d+')):
            href = "http://wave.pref.wakayama.lg.jp/news/kensei/" + a['href'].lstrip('/')
            if href in seen:
                continue
            raw_t = re.sub(r'\s+', ' ', a.get_text()).strip()
            # 末尾の担当課表記 ( 〇〇課 ) を整理
            title = re.sub(r'\(\s*[^)]+\)$', '', raw_t).strip()
            if len(title) < 8 or any(skip in title for skip in ['知事日程', '予定表', '行事予定']):
                continue
            seen.add(href)
            items.append({
                'title': title,
                'url': href,
                'source': '和歌山県政ニュース',
                'article_date': now_str,
                'published_at': now_pub
            })
            if len(items) >= 12:
                break
        print(f"和歌山県政ニュース から {len(items)} 件を取得しました。")
        return items
    except Exception as e:
        print(f"Wakayama Pref fetch error: {e}")
        return []

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

def compute_article_importance(item: Dict[str, Any]) -> int:
    """記事の注目度・重要度スコアを算出（複数社報道・一次情報源・重要キーワード・要約充実度）"""
    score = 0
    related_cnt = len(item.get("related_articles", []))
    score += related_cnt * 15

    source = item.get("source", "")
    if any(s in source for s in ["紀伊民報", "WBS", "和歌山放送", "わかやま新報", "日高新報", "和歌山県政", "NHK", "毎日", "読売", "朝日", "産経"]):
        score += 5

    title = item.get("title", "")
    summary = item.get("summary", "")
    combined = title + " " + summary

    # 注目度の高いキーワード
    high_impact_kws = [
        "全国", "初", "決定", "発表", "逮捕", "警報", "クマ", "熊", "白浜", "パンダ",
        "高野山", "熊野", "世界遺産", "知事", "予算", "開通", "開業", "優勝", "新宮",
        "田辺", "和歌山市", "ロケット", "カイロス", "串本", "アドベンチャーワールド", "育樹祭"
    ]
    matched_impact = sum(1 for kw in high_impact_kws if kw in combined)
    score += min(matched_impact * 3, 15)

    # 要約の行数（3行揃っている記事を優遇）
    bullet_cnt = len([l for l in summary.splitlines() if l.strip().startswith('・')])
    if bullet_cnt >= 3:
        score += 6
    elif bullet_cnt == 2:
        score += 3

    return score

def cluster_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同じトピックの記事を1つの代表記事にまとめ、重要度スコアと注目フラグを付与"""
    clusters: List[Dict[str, Any]] = []
    for item in articles:
        item["summary"] = sanitize_existing_summary(item.get("title", ""), item.get("summary", ""))
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

    # 各クラスタの重要度スコアを算出し、上位記事に注目フラグ (is_featured) を付与
    for c in clusters:
        c["importance_score"] = compute_article_importance(c)
        c["is_featured"] = False

    if clusters:
        ranked = sorted(clusters, key=lambda x: (x.get("importance_score", 0), x.get("published_at", "")), reverse=True)
        featured_limit = 3 if len(clusters) >= 6 else (2 if len(clusters) >= 3 else 1)
        featured_count = 0
        for r in ranked:
            if r.get("importance_score", 0) >= 12 and featured_count < featured_limit:
                r["is_featured"] = True
                featured_count += 1

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
    known_urls = set()
    
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
                    seen_urls = {a["url"] for a in articles_by_date[date_str]}
                    for item in existing:
                        u = item.get("url")
                        if u:
                            known_urls.add(u)
                        for rel in item.get("related_articles", []):
                            if rel.get("url"):
                                known_urls.add(rel.get("url"))
                        if u and u not in seen_urls:
                            articles_by_date[date_str].append(item)
                            seen_urls.add(u)
            except Exception as e:
                print(f"Error loading {fn}: {e}")

    # 1. 和歌山県全30市町村・6郡を網羅するGoogle News収集クエリ
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
    
    for q in queries:
        encoded = urllib.parse.quote(q)
        rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=ja&gl=JP&ceid=JP:ja"
        feed = feedparser.parse(rss_url)
        for e in feed.entries[:25]:
            link = e.get('link')
            if link and link not in seen_links:
                seen_links.add(link)
                raw_entries.append(e)

    # 2. 地元有力メディア・県庁から直接取得（紀伊民報・WBS和歌山放送・わかやま新報・日高新報・和歌山県政ニュース）
    local_media_items = []
    local_media_items.extend(fetch_agara_items())
    local_media_items.extend(fetch_wbs_items())
    local_media_items.extend(fetch_wakayama_shimpo_items())
    local_media_items.extend(fetch_hidaka_shimpo_items())
    local_media_items.extend(fetch_wakayama_pref_items())

    new_local_items = [it for it in local_media_items if it.get('url') not in known_urls]

    print(f"情報ソース取得完了: Google News {len(raw_entries)} 件, 地元専門メディア/県政 {len(new_local_items)} 件（新規）")
    print("並列解析および高度要約生成を開始...")
    
    new_articles = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = []
        for entry in raw_entries:
            futures.append(executor.submit(process_single_entry, entry, gemini_key))
        for item in new_local_items:
            futures.append(executor.submit(
                process_article_item,
                item['url'],
                item['title'],
                item['source'],
                item['article_date'],
                item['published_at'],
                gemini_key,
                False  # 地元専門メディアは和歌山確定のため無条件採用
            ))
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
