import sys
import io
import database

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

stats = database.get_stats()
print("Stats:", stats)

dates = database.get_available_dates()
print("Available Dates:", dates)

if dates:
    latest_date = dates[0]['article_date']
    articles = database.get_articles_by_date(latest_date)
    print(f"\n--- {latest_date} の記事数: {len(articles)} 件 ---")
    for a in articles[:3]:
        print(f"\n[ID: {a['id']}] [{a['category']}] {a['title']}")
        print(f"媒体: {a['source']} | 公開日時: {a['published_at']}")
        print(f"URL: {a['url']}")
        print(f"要約:\n{a['summary']}")
