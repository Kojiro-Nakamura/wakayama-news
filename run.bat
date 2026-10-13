@echo off
chcp 65001 > nul
title 和歌山デイリーニュース 起動ランチャー

echo ========================================================
echo    和歌山デイリーニュース (Wakayama Daily News)
echo    完全無料・日別アーカイブ＆30秒要約リーダー
echo ========================================================
echo.
echo アプリケーションを起動しています...
echo ブラウザで http://localhost:8000 が開きます。
echo 終了するときはこの黒い画面（コマンドプロンプト）を閉じるか Ctrl+C を押してください。
echo.

cd /d %~dp0

if not exist ".venv\Scripts\python.exe" (
    echo [エラー] 仮想環境が見つかりません。セットアップを実行してください。
    pause
    exit /b 1
)

start "" http://localhost:8000
.\.venv\Scripts\uvicorn main:app --host 127.0.0.1 --port 8000
pause
