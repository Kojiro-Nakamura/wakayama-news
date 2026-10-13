import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional, Any

DB_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DB_DIR, "wakayama_news.db")

def init_db():
    """データベースとテーブルの初期化"""
    os.makedirs(DB_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 記事テーブル
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_date TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                google_url TEXT,
                source TEXT,
                published_at TEXT,
                summary TEXT,
                summary_type TEXT DEFAULT 'auto',
                category TEXT DEFAULT '一般',
                created_at TEXT NOT NULL
            )
        """)
        
        # 日付やURL検索用のインデックス
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_article_date ON articles (article_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_article_url ON articles (url)")
        
        # アプリ設定テーブル
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        conn.commit()

def get_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def insert_article(
    article_date: str,
    title: str,
    url: str,
    google_url: str = "",
    source: str = "",
    published_at: str = "",
    summary: str = "",
    summary_type: str = "auto",
    category: str = "一般"
) -> bool:
    """記事を保存。重複URLの場合は挿入せずFalseを返す"""
    now = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO articles 
                (article_date, title, url, google_url, source, published_at, summary, summary_type, category, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (article_date, title, url, google_url, source, published_at, summary, summary_type, category, now))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def get_articles_by_date(target_date: str, category: Optional[str] = None, search_query: Optional[str] = None) -> List[Dict[str, Any]]:
    """指定した日付の記事一覧を取得"""
    with get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM articles WHERE article_date = ?"
        params: List[Any] = [target_date]
        
        if category and category != "all":
            query += " AND category = ?"
            params.append(category)
            
        if search_query:
            query += " AND (title LIKE ? OR summary LIKE ?)"
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard])
            
        query += " ORDER BY published_at DESC, id DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def get_available_dates() -> List[Dict[str, Any]]:
    """記事が存在する日付とその件数のリストを取得（最新順）"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT article_date, COUNT(*) as count 
            FROM articles 
            GROUP BY article_date 
            ORDER BY article_date DESC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def search_articles(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """全期間からキーワード検索"""
    with get_connection() as conn:
        cursor = conn.cursor()
        wildcard = f"%{query}%"
        cursor.execute("""
            SELECT * FROM articles 
            WHERE title LIKE ? OR summary LIKE ? 
            ORDER BY article_date DESC, published_at DESC 
            LIMIT ?
        """, (wildcard, wildcard, limit))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def get_stats() -> Dict[str, Any]:
    """統計情報を取得"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total_articles FROM articles")
        total = cursor.fetchone()["total_articles"]
        
        cursor.execute("SELECT COUNT(DISTINCT article_date) as total_days FROM articles")
        days = cursor.fetchone()["total_days"]
        
        cursor.execute("SELECT MAX(created_at) as last_updated FROM articles")
        last_updated = cursor.fetchone()["last_updated"]
        
        return {
            "total_articles": total,
            "total_days": days,
            "last_updated": last_updated
        }

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default

def set_setting(key: str, value: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        conn.commit()
