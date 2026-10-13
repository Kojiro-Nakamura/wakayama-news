import os
import threading
import time
from typing import Optional
from fastapi import FastAPI, Query, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import database
import collector

app = FastAPI(title="和歌山デイリーニュース (Wakayama Daily News)")

# データベース初期化
database.init_db()

# 静的ファイル用のディレクトリ
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# バックグラウンド定期収集スレッド
def background_periodic_collector():
    """アプリ起動中に数時間おきに自動で最新ニュースを取得"""
    while True:
        try:
            # 6時間（21600秒）ごとに自動巡回
            time.sleep(21600)
            print("[Auto-Collector] 定期ニュース収集を実行中...")
            collector.collect_news()
            print("[Auto-Collector] 定期ニュース収集完了")
        except Exception as e:
            print(f"[Auto-Collector Error]: {e}")
            time.sleep(60)

# アプリ起動時にバックグラウンドスレッドを開始
periodic_thread = threading.Thread(target=background_periodic_collector, daemon=True)
periodic_thread.start()

class SettingsUpdate(BaseModel):
    gemini_api_key: Optional[str] = None

@app.get("/api/dates")
def get_dates():
    """記事が存在する日付リストを返す"""
    dates = database.get_available_dates()
    return {"dates": dates}

@app.get("/api/articles")
def get_articles(
    date: Optional[str] = Query(None, description="日付 (YYYY-MM-DD)"),
    category: Optional[str] = Query(None, description="カテゴリ"),
    q: Optional[str] = Query(None, description="検索キーワード")
):
    """指定日またはキーワードでの記事一覧を返す"""
    # 日付が指定されていない場合は最新の日付を取得
    if not date:
        dates = database.get_available_dates()
        if dates:
            date = dates[0]["article_date"]
        else:
            return {"date": None, "articles": [], "total": 0}

    articles = database.get_articles_by_date(date, category=category, search_query=q)
    return {
        "date": date,
        "articles": articles,
        "total": len(articles)
    }

@app.get("/api/search")
def search_all_articles(q: str = Query(..., description="検索キーワード")):
    """全期間からのキーワード検索"""
    articles = database.search_articles(q)
    return {
        "query": q,
        "articles": articles,
        "total": len(articles)
    }

@app.post("/api/collect")
def trigger_collection():
    """最新ニュースの手動取得を実行"""
    result = collector.collect_news(max_items=25)
    return result

@app.get("/api/stats")
def get_statistics():
    """統計情報を返す"""
    stats = database.get_stats()
    return stats

@app.get("/api/settings")
def get_settings():
    """設定状態を返す（キーそのものは秘匿し、設定されているかどうかを返す）"""
    key = database.get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    return {
        "has_gemini_key": bool(key),
        "key_hint": f"...{key[-4:]}" if len(key) >= 4 else ""
    }

@app.post("/api/settings")
def update_settings(payload: SettingsUpdate):
    """Gemini APIキーを設定"""
    if payload.gemini_api_key is not None:
        database.set_setting("gemini_api_key", payload.gemini_api_key.strip())
    return {"status": "success", "message": "設定を保存しました"}

# フロントエンドの静的ファイルマウント
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def serve_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "和歌山ニュースAPIは正常に動作しています。フロントエンドを準備中です。"}

if __name__ == "__main__":
    import uvicorn
    # 初回起動時にDBが空なら一度収集を実行
    stats = database.get_stats()
    if stats["total_articles"] == 0:
        print("初回ニュース収集を実行中...")
        collector.collect_news()
    
    print("サーバーを起動します: http://localhost:8000")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
