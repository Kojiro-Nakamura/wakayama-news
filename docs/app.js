// 和歌山デイリーニュース 静的サイト (GitHub Pages対応) フロントエンドJS

let currentDate = null;
let currentCategory = 'all';
let currentSortMode = 'featured';
let searchQuery = '';
let availableDates = [];
let dateArticlesCache = {};
let allArticlesSearchCache = null;

// DOM要素
const dateListEl = document.getElementById('dateList');
const datePickerInput = document.getElementById('datePickerInput');
const articlesContainerEl = document.getElementById('articlesContainer');
const currentDisplayDateEl = document.getElementById('currentDisplayDate');
const currentCountBadgeEl = document.getElementById('currentCountBadge');
const statArticlesEl = document.getElementById('statArticles');
const statDaysEl = document.getElementById('statDays');
const statUpdatedEl = document.getElementById('statUpdated');
const searchInput = document.getElementById('searchInput');
const categoryFilterEl = document.getElementById('categoryFilter');

// 日付ナビゲーション ＆ モバイルアコーディオン要素
const dateArchiveToggleBtn = document.getElementById('dateArchiveToggleBtn');
const dateArchiveContent = document.getElementById('dateArchiveContent');
const dateArchiveToggleLabel = document.getElementById('dateArchiveToggleLabel');
const dateArchiveChevron = document.getElementById('dateArchiveChevron');
const prevDateBtn = document.getElementById('prevDateBtn');
const nextDateBtn = document.getElementById('nextDateBtn');
const bottomPrevDateBtn = document.getElementById('bottomPrevDateBtn');
const bottomNextDateBtn = document.getElementById('bottomNextDateBtn');
const bottomPrevDateLabel = document.getElementById('bottomPrevDateLabel');
const bottomNextDateLabel = document.getElementById('bottomNextDateLabel');
const dateNavControls = document.getElementById('dateNavControls');
const bottomDateNav = document.getElementById('bottomDateNav');

// カテゴリ色マッピング
const categoryBadgeClasses = {
  '観光・文化': 'bg-emerald-50 text-emerald-700 border-emerald-200',
  '社会・事件': 'bg-rose-50 text-rose-700 border-rose-200',
  '政治・行政': 'bg-indigo-50 text-indigo-700 border-indigo-200',
  'スポーツ': 'bg-blue-50 text-blue-700 border-blue-200',
  '経済・産業': 'bg-amber-50 text-amber-700 border-amber-200',
  '地域・一般': 'bg-slate-100 text-slate-700 border-slate-200'
};

// 初期化
document.addEventListener('DOMContentLoaded', async () => {
  if (window.lucide) lucide.createIcons();
  setupEventListeners();
  await loadInitialData();
});

// イベントリスナー設定
function setupEventListeners() {
  // 日付ピッカー変更
  if (datePickerInput) {
    datePickerInput.addEventListener('change', (e) => {
      if (e.target.value) {
        selectDate(e.target.value);
      }
    });
  }

  // 検索入力
  let searchTimeout = null;
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      searchQuery = e.target.value.trim();
      searchClearBtn.classList.toggle('hidden', searchQuery.length === 0);
      document.querySelectorAll('.region-tag').forEach(b => {
        if (b.dataset.region === searchQuery) {
          b.classList.remove('bg-slate-100', 'text-slate-600');
          b.classList.add('bg-orange-500', 'text-white');
        } else {
          b.classList.remove('bg-orange-500', 'text-white');
          b.classList.add('bg-slate-100', 'text-slate-600');
        }
      });
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        loadArticles();
      }, 200);
    });

    searchClearBtn.addEventListener('click', () => {
      searchInput.value = '';
      searchQuery = '';
      searchClearBtn.classList.add('hidden');
      document.querySelectorAll('.region-tag').forEach(b => {
        b.classList.remove('bg-orange-500', 'text-white');
        b.classList.add('bg-slate-100', 'text-slate-600');
      });
      loadArticles();
    });
  }

  // 市町村・地域タグ選択
  const regionTagsEl = document.getElementById('regionTags');
  if (regionTagsEl) {
    regionTagsEl.addEventListener('click', (e) => {
      const btn = e.target.closest('.region-tag');
      if (!btn) return;
      const region = btn.dataset.region;
      if (searchInput.value === region) {
        // 解除
        searchInput.value = '';
        searchQuery = '';
        searchClearBtn.classList.add('hidden');
        btn.classList.remove('bg-orange-500', 'text-white');
        btn.classList.add('bg-slate-100', 'text-slate-600');
      } else {
        document.querySelectorAll('.region-tag').forEach(b => {
          b.classList.remove('bg-orange-500', 'text-white');
          b.classList.add('bg-slate-100', 'text-slate-600');
        });
        btn.classList.remove('bg-slate-100', 'text-slate-600');
        btn.classList.add('bg-orange-500', 'text-white');
        searchInput.value = region;
        searchQuery = region;
        searchClearBtn.classList.remove('hidden');
      }
      loadArticles();
    });
  }

  // カテゴリ選択
  if (categoryFilterEl) {
    categoryFilterEl.addEventListener('click', (e) => {
      const btn = e.target.closest('.cat-pill');
      if (!btn) return;
      
      document.querySelectorAll('.cat-pill').forEach(b => {
        b.classList.remove('bg-slate-900', 'text-white', 'active');
        b.classList.add('bg-slate-100', 'text-slate-600');
      });
      btn.classList.remove('bg-slate-100', 'text-slate-600');
      btn.classList.add('bg-slate-900', 'text-white', 'active');

      currentCategory = btn.dataset.category;
      loadArticles();
    });
  }

  // 並び順切り替え（注目順 / 新着順）
  const sortModeToggleEl = document.getElementById('sortModeToggle');
  if (sortModeToggleEl) {
    sortModeToggleEl.addEventListener('click', (e) => {
      const btn = e.target.closest('.sort-btn');
      if (!btn) return;
      document.querySelectorAll('.sort-btn').forEach(b => {
        b.classList.remove('bg-white', 'text-orange-700', 'shadow-sm', 'active');
        b.classList.add('text-slate-600');
      });
      btn.classList.remove('text-slate-600');
      btn.classList.add('bg-white', 'text-orange-700', 'shadow-sm', 'active');
      currentSortMode = btn.dataset.sort;
      loadArticles();
    });
  }

  // モバイル用: 日付アーカイブアコーディオンの開閉トグル
  if (dateArchiveToggleBtn && dateArchiveContent) {
    dateArchiveToggleBtn.addEventListener('click', () => {
      // スマホ幅（md未満）のときのみトグル
      if (window.innerWidth < 768) {
        const isHidden = dateArchiveContent.classList.contains('hidden');
        if (isHidden) {
          dateArchiveContent.classList.remove('hidden');
          if (dateArchiveToggleLabel) dateArchiveToggleLabel.textContent = '閉じる';
          if (dateArchiveChevron) dateArchiveChevron.classList.add('rotate-180');
        } else {
          dateArchiveContent.classList.add('hidden');
          if (dateArchiveToggleLabel) dateArchiveToggleLabel.textContent = '開く';
          if (dateArchiveChevron) dateArchiveChevron.classList.remove('rotate-180');
        }
      }
    });
  }
}

// 初期データ（index.json）読み込み
async function loadInitialData() {
  try {
    const res = await fetch('./data/index.json?v=' + Date.now());
    if (!res.ok) throw new Error('Failed to load index.json');
    const data = await res.json();

    // 統計反映
    if (data.stats) {
      statArticlesEl.textContent = `蓄積記事: ${data.stats.total_articles.toLocaleString()} 件`;
      statDaysEl.textContent = `アーカイブ: ${data.stats.total_days} 日分`;
      if (data.stats.last_updated) {
        const d = new Date(data.stats.last_updated);
        statUpdatedEl.textContent = `自動更新: ${d.toLocaleDateString('ja-JP')} ${d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })}`;
      }
    }

    // 日付リスト
    availableDates = data.dates || [];
    renderDateList();

    // 最新日付を選択
    if (availableDates.length > 0) {
      currentDate = availableDates[0].article_date;
      if (datePickerInput) datePickerInput.value = currentDate;
      await loadArticles();
    }
  } catch (err) {
    console.error('初期データ読み込みエラー:', err);
    articlesContainerEl.innerHTML = `
      <div class="p-8 text-center text-rose-500 text-sm bg-rose-50 rounded-2xl border border-rose-200">
        データの読み込みに失敗しました。ページを再読み込みしてください。
      </div>
    `;
  }
}

// 日付サイドバーの描画
function renderDateList() {
  dateListEl.innerHTML = '';
  if (availableDates.length === 0) {
    dateListEl.innerHTML = '<div class="p-3 text-center text-xs text-slate-400">記事がまだありません。</div>';
    return;
  }

  availableDates.forEach((item, index) => {
    const btn = document.createElement('button');
    const isActive = item.article_date === currentDate || (!currentDate && index === 0);
    btn.className = `date-item w-full flex items-center justify-between px-3 py-2 text-xs rounded-xl border border-transparent hover:bg-slate-100 transition-all text-left ${isActive ? 'active' : 'text-slate-700'}`;
    
    const formattedDate = formatDisplayDate(item.article_date);
    const isToday = isTodayDate(item.article_date);
    
    btn.innerHTML = `
      <div class="flex items-center gap-1.5">
        <span class="font-medium">${formattedDate}</span>
        ${isToday ? '<span class="text-[10px] px-1.5 py-0.2 bg-orange-200 text-orange-800 rounded font-bold">今日</span>' : ''}
      </div>
      <span class="text-[11px] px-2 py-0.5 rounded-full bg-slate-200/70 text-slate-600 font-semibold">${item.count}件</span>
    `;

    btn.addEventListener('click', () => {
      selectDate(item.article_date);
    });

    dateListEl.appendChild(btn);
  });
}

// 日付選択
function selectDate(dateStr) {
  currentDate = dateStr;
  if (datePickerInput) datePickerInput.value = dateStr;

  // モバイル表示時は、日付を選択したら自動的にアコーディオンを閉じる
  if (window.innerWidth < 768 && dateArchiveContent && !dateArchiveContent.classList.contains('hidden')) {
    dateArchiveContent.classList.add('hidden');
    if (dateArchiveToggleLabel) dateArchiveToggleLabel.textContent = '開く';
    if (dateArchiveChevron) dateArchiveChevron.classList.remove('rotate-180');
  }

  // 日付リストのアクティブ表示更新
  document.querySelectorAll('.date-item').forEach(el => {
    el.classList.remove('active');
  });
  const match = [...document.querySelectorAll('.date-item')].find(el => el.textContent.includes(formatDisplayDate(dateStr)));
  if (match) match.classList.add('active');

  loadArticles();
}

// 記事取得とフィルタリング
async function loadArticles() {
  articlesContainerEl.innerHTML = `
    <div class="p-12 text-center text-slate-400 text-xs bg-white rounded-2xl border border-slate-200 flex flex-col items-center justify-center gap-2">
      <div class="w-6 h-6 border-2 border-orange-500 border-t-transparent rounded-full animate-spin"></div>
      <span>記事を読み込み中...</span>
    </div>
  `;

  try {
    let articles = [];

    // 検索クエリがある場合で、全期間検索したい場合
    if (searchQuery && !currentDate) {
      if (!allArticlesSearchCache) {
        const sRes = await fetch('./data/search_index.json?v=' + Date.now());
        allArticlesSearchCache = await sRes.json();
      }
      articles = allArticlesSearchCache;
    } else if (currentDate) {
      // 特定日のJSONをキャッシュまたはfetch
      if (!dateArticlesCache[currentDate]) {
        const res = await fetch(`./data/dates/${currentDate}.json?v=` + Date.now());
        if (res.ok) {
          dateArticlesCache[currentDate] = await res.json();
        } else {
          dateArticlesCache[currentDate] = [];
        }
      }
      articles = dateArticlesCache[currentDate] || [];
    }

    // フィルタリング処理
    let filtered = [...articles];

    // カテゴリフィルター
    if (currentCategory && currentCategory !== 'all') {
      filtered = filtered.filter(a => a.category === currentCategory);
    }

    // 検索キーワードフィルター
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(a => 
        (a.title && a.title.toLowerCase().includes(q)) || 
        (a.summary && a.summary.toLowerCase().includes(q)) ||
        (a.source && a.source.toLowerCase().includes(q))
      );
    }

    // 並び替え処理（注目順 / 新着順）
    if (currentSortMode === 'featured') {
      filtered.sort((a, b) => {
        const featDiff = (b.is_featured ? 1 : 0) - (a.is_featured ? 1 : 0);
        if (featDiff !== 0) return featDiff;
        const scoreDiff = (b.importance_score || 0) - (a.importance_score || 0);
        if (scoreDiff !== 0) return scoreDiff;
        return (b.published_at || '').localeCompare(a.published_at || '');
      });
    } else {
      filtered.sort((a, b) => (b.published_at || '').localeCompare(a.published_at || ''));
    }

    // ヘッダー情報更新
    currentDisplayDateEl.textContent = currentDate ? `${formatDisplayDate(currentDate)} のニュース` : '全期間検索結果';
    currentCountBadgeEl.textContent = `${filtered.length} 件`;

    // 前日・翌日ナビゲーションの更新
    updateDateNav();

    if (filtered.length === 0) {
      articlesContainerEl.innerHTML = `
        <div class="p-12 text-center text-slate-500 text-sm bg-white rounded-2xl border border-slate-200/80 shadow-sm space-y-2">
          <i data-lucide="inbox" class="w-8 h-8 text-slate-300 mx-auto"></i>
          <p class="font-medium text-slate-700">条件に合致するニュースが見つかりませんでした</p>
          <p class="text-xs text-slate-400">別の日付を選ぶか、検索条件を変更してください。</p>
        </div>
      `;
      if (window.lucide) lucide.createIcons();
      return;
    }

    // 描画
    articlesContainerEl.innerHTML = filtered.map(renderArticleCard).join('');
    if (window.lucide) lucide.createIcons();

  } catch (err) {
    console.error('記事読み込みエラー:', err);
    articlesContainerEl.innerHTML = `
      <div class="p-8 text-center text-rose-500 text-sm bg-rose-50 rounded-2xl border border-rose-200">
        記事の取得に失敗しました。
      </div>
    `;
  }
}

// 前日・翌日ナビゲーションボタンの更新
function updateDateNav() {
  if (!availableDates || availableDates.length === 0 || !currentDate) {
    if (dateNavControls) dateNavControls.classList.add('hidden');
    if (bottomDateNav) bottomDateNav.classList.add('hidden');
    return;
  }

  if (dateNavControls) dateNavControls.classList.remove('hidden');
  if (bottomDateNav) bottomDateNav.classList.remove('hidden');

  const dateStrings = availableDates.map(d => d.article_date);
  const currIdx = dateStrings.indexOf(currentDate);

  // availableDatesは降順（新しい順）なので：
  // 前日（1つ古い日付）は currIdx + 1
  // 翌日（1つ新しい日付）は currIdx - 1
  const prevDate = currIdx !== -1 && currIdx < dateStrings.length - 1 ? dateStrings[currIdx + 1] : null;
  const nextDate = currIdx > 0 ? dateStrings[currIdx - 1] : null;

  // 前日ボタン
  [prevDateBtn, bottomPrevDateBtn].forEach(btn => {
    if (!btn) return;
    if (prevDate) {
      btn.disabled = false;
      btn.onclick = () => selectDate(prevDate);
    } else {
      btn.disabled = true;
      btn.onclick = null;
    }
  });

  if (bottomPrevDateLabel) {
    bottomPrevDateLabel.textContent = prevDate ? `前日 (${formatShortDate(prevDate)})` : '前日なし';
  }

  // 翌日ボタン
  [nextDateBtn, bottomNextDateBtn].forEach(btn => {
    if (!btn) return;
    if (nextDate) {
      btn.disabled = false;
      btn.onclick = () => selectDate(nextDate);
    } else {
      btn.disabled = true;
      btn.onclick = null;
    }
  });

  if (bottomNextDateLabel) {
    bottomNextDateLabel.textContent = nextDate ? `翌日 (${formatShortDate(nextDate)})` : '翌日なし';
  }
}

function formatShortDate(dateStr) {
  if (!dateStr) return '';
  const parts = dateStr.split('-');
  if (parts.length === 3) {
    return `${parseInt(parts[1], 10)}/${parseInt(parts[2], 10)}`;
  }
  return dateStr;
}

// 記事カード1枚のHTML生成
function renderArticleCard(a) {
  const catClass = categoryBadgeClasses[a.category] || categoryBadgeClasses['地域・一般'];
  
  const rawSummary = a.summary || '';
  const summaryPoints = rawSummary
    .split('\n')
    .map(line => line.trim())
    .filter(line => line.length > 0)
    .map(line => line.replace(/^[・\-\*]\s*/, ''));

  const summaryHtml = summaryPoints.map(point => `
    <li class="flex items-start gap-2 text-slate-700 text-xs sm:text-sm leading-relaxed">
      <span class="text-orange-500 font-bold shrink-0 mt-0.5">•</span>
      <span>${escapeHtml(point)}</span>
    </li>
  `).join('');

  const isAi = a.summary_type === 'ai';
  const isFeatured = Boolean(a.is_featured);
  const relatedCount = Array.isArray(a.related_articles) ? a.related_articles.length : 0;

  const cardBorderClass = isFeatured
    ? 'border-orange-300 ring-1 ring-orange-200/70 bg-gradient-to-b from-orange-50/25 to-white'
    : 'border-slate-200/80 bg-white';

  return `
    <article class="${cardBorderClass} rounded-2xl border p-5 shadow-sm hover:shadow-md transition-all space-y-4">
      
      <!-- 上部メタ情報 -->
      <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div class="flex flex-wrap items-center gap-1.5">
          ${isFeatured ? `
            <span class="px-2.5 py-0.5 rounded-full bg-gradient-to-r from-orange-500 to-amber-500 text-white text-[11px] font-bold shadow-sm flex items-center gap-1">
              🔥 注目ピックアップ
            </span>
          ` : ''}
          ${relatedCount >= 1 ? `
            <span class="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300 text-[11px] font-bold">
              📰 ${1 + relatedCount}社が報道
            </span>
          ` : ''}
          <span class="px-2.5 py-0.5 rounded-full border text-[11px] font-semibold ${catClass}">
            ${escapeHtml(a.category)}
          </span>
          <span class="font-medium text-slate-600 flex items-center gap-1">
            <i data-lucide="newspaper" class="w-3 h-3 text-slate-400"></i>
            ${escapeHtml(a.source || '配信元')}
          </span>
        </div>
        <span class="text-slate-400 text-[11px] font-en flex items-center gap-1 font-medium">
          <i data-lucide="clock" class="w-3 h-3 text-slate-400"></i>
          ${escapeHtml(a.published_at || '')}
        </span>
      </div>

      <!-- 記事タイトル -->
      <a href="${escapeHtml(a.url)}" target="_blank" rel="noopener noreferrer" class="block group/title">
        <h3 class="text-base sm:text-lg font-bold leading-snug group-hover/title:text-orange-600 hover:underline decoration-orange-400 underline-offset-4 transition-colors">
          ${escapeHtml(a.title)}
        </h3>
      </a>

      <!-- 30秒要約ボックス -->
      <div class="summary-box p-4 rounded-xl space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-xs font-bold text-orange-950 flex items-center gap-1.5 tracking-tight">
            <i data-lucide="zap" class="w-3.5 h-3.5 text-orange-600 fill-orange-500"></i>
            さっと読める要約ポイント
          </span>
          ${isAi ? `
            <span class="text-[10px] font-semibold px-2 py-0.5 bg-gradient-to-r from-purple-100 to-indigo-100 text-indigo-700 rounded-full border border-indigo-200 flex items-center gap-1">
              ✨ AI要約
            </span>
          ` : `
            <span class="text-[10px] text-slate-400 font-en">SUMMARY</span>
          `}
        </div>
        <ul class="space-y-2 pl-1">
          ${summaryHtml}
        </ul>
      </div>

      <!-- 関連報道（同一トピック）のアコーディオン -->
      ${a.related_articles && a.related_articles.length > 0 ? `
        <div class="pt-3 border-t border-slate-100">
          <button 
            type="button"
            onclick="toggleRelated(this)" 
            class="w-full flex items-center justify-between py-2 px-3.5 rounded-xl bg-orange-50/70 hover:bg-orange-100/80 border border-orange-200/70 text-xs text-orange-950 font-medium transition-all group"
          >
            <span class="flex items-center gap-2">
              <span class="flex items-center justify-center w-5 h-5 rounded-md bg-orange-200 text-orange-800 text-[10px] font-bold font-en">
                +${a.related_articles.length}
              </span>
              <span class="font-bold">他 ${a.related_articles.length} 社の同一トピック報道（${a.related_articles.map(r => escapeHtml(r.source)).slice(0, 3).join(', ')}${a.related_articles.length > 3 ? ' 等' : ''}）</span>
            </span>
            <span class="text-[11px] text-orange-700 font-semibold flex items-center gap-1">
              <span class="toggle-label">開く</span>
              <i data-lucide="chevron-down" class="w-3.5 h-3.5 transition-transform duration-200 chevron-icon"></i>
            </span>
          </button>
          <div class="related-articles-list hidden space-y-2 mt-2.5 pt-1 px-1">
            ${a.related_articles.map(r => `
              <a 
                href="${escapeHtml(r.url)}" 
                target="_blank" 
                rel="noopener noreferrer" 
                class="flex items-center justify-between p-2.5 rounded-xl bg-slate-50 hover:bg-orange-50 border border-slate-200/60 hover:border-orange-200 transition-all text-xs group/item"
              >
                <div class="flex items-center gap-2 min-w-0 pr-2">
                  <span class="px-2 py-0.5 rounded-md bg-white border border-slate-200 text-slate-700 text-[10px] font-semibold shrink-0">
                    ${escapeHtml(r.source || '配信元')}
                  </span>
                  <span class="text-slate-700 group-hover/item:text-orange-600 font-medium truncate">
                    ${escapeHtml(r.title)}
                  </span>
                </div>
                <span class="text-[11px] text-slate-400 group-hover/item:text-orange-600 shrink-0 flex items-center gap-0.5 font-medium">
                  <span>元記事</span>
                  <i data-lucide="arrow-up-right" class="w-3 h-3"></i>
                </span>
              </a>
            `).join('')}
          </div>
        </div>
      ` : ''}

      <!-- 下部アクション: 元記事リンク -->
      <div class="flex items-center justify-between pt-1">
        <div class="text-[11px] text-slate-400">
          公式メディアで全文・写真を確認
        </div>
        <a 
          href="${escapeHtml(a.url)}" 
          target="_blank" 
          rel="noopener noreferrer" 
          class="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-slate-900 hover:bg-orange-600 active:scale-95 text-white transition-all shadow-sm hover:shadow"
        >
          <span>元記事を読む</span>
          <i data-lucide="arrow-up-right" class="w-3.5 h-3.5"></i>
        </a>
      </div>

    </article>
  `;
}

// 関連報道アコーディオンの開閉
window.toggleRelated = function(btn) {
  const container = btn.nextElementSibling;
  const chevron = btn.querySelector('.chevron-icon');
  const label = btn.querySelector('.toggle-label');
  const isHidden = container.classList.contains('hidden');
  
  if (isHidden) {
    container.classList.remove('hidden');
    chevron.classList.add('rotate-180');
    label.textContent = '閉じる';
  } else {
    container.classList.add('hidden');
    chevron.classList.remove('rotate-180');
    label.textContent = '開く';
  }
};

function formatDisplayDate(dateStr) {
  if (!dateStr) return '';
  const parts = dateStr.split('-');
  if (parts.length === 3) {
    return `${parts[0]}年${parseInt(parts[1], 10)}月${parseInt(parts[2], 10)}日`;
  }
  return dateStr;
}

function isTodayDate(dateStr) {
  const today = new Date();
  const y = today.getFullYear();
  const m = String(today.getMonth() + 1).padStart(2, '0');
  const d = String(today.getDate()).padStart(2, '0');
  return dateStr === `${y}-${m}-${d}`;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
