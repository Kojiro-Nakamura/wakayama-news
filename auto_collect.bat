@echo off
chcp 65001 > nul
cd /d %~dp0

echo [%date% %time%] 和歌山ニュースの自動巡回収集を開始します... >> data\auto_collect.log
.\.venv\Scripts\python -c "import collector; res = collector.collect_news(); print(f'収集結果: {res}')" >> data\auto_collect.log 2>&1
echo [%date% %time%] 完了 >> data\auto_collect.log
