// 和歌山デイリーニュース フロントエンドJS

let currentDate = null;
let currentCategory = 'all';
let searchQuery = '';
let availableDates = [];

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
const searchClearBtn = document.getElementById('searchClearBtn');
const categoryFilterEl = document.getElementById('categoryFilter');
const collectBtn = document.getElementById('collectBtn');
const refreshIcon = document.getElementById('refreshIcon');
const settingsBtn = document.getElementById('settingsBtn');
const settingsModal = document.getElementById('settingsModal');
const closeSettingsBtn = document.getElementById('closeSettingsBtn');
const cancelSettingsBtn = document.getElementById('cancelSettingsBtn');
const saveSettingsBtn = document.getElementById('saveSettingsBtn');
const geminiKeyInput = document.getElementById('geminiKeyInput');
const apiKeyStatusEl = document.getElementById('apiKeyStatus');
const toastEl = document.getElementById('toast');
const toastMsgEl = document.getElementById('toastMsg');

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
  await loadStats();
  await loadDates();
  await loadSettings();
  setupEventListeners();
});

// イベントリスナー設定
function setupEventListeners() {
  // 日付ピッカー変更
  datePickerInput.addEventListener('change', (e) => {
    if (e.target.value) {
      selectDate(e.target.value);
    }
  });

  // 検索入力
  let searchTimeout = null;
  searchInput.addEventListener('input', (e) => {
    searchQuery = e.target.value.trim();
    searchClearBtn.classList.toggle('hidden', searchQuery.length === 0);
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      loadArticles();
    }, 250);
  });

  searchClearBtn.addEventListener('click', () => {
    searchInput.value = '';
    searchQuery = '';
    searchClearBtn.classList.add('hidden');
    loadArticles();
  });

  // カテゴリ選択
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

  // ニュース手動取得
  collectBtn.addEventListener('click', async () => {
    collectBtn.disabled = true;
    refreshIcon.classList.add('animate-spin-fast');
    showToast('最新ニュースを巡回取得しています...');

    try {
      const res = await fetch('/api/collect', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        showToast(`取得完了！新着: ${data.new_articles}件 (合計チェック: ${data.total_checked}件)`);
        await loadStats();
        await loadDates();
        await loadArticles();
      } else {
        showToast('取得中にエラーが発生しました');
      }
    } catch (err) {
      console.error(err);
      showToast('通信エラーが発生しました');
    } finally {
      collectBtn.disabled = false;
      refreshIcon.classList.remove('animate-spin-fast');
    }
  });

  // 設定モーダル
  settingsBtn.addEventListener('click', () => {
    settingsModal.classList.remove('hidden');
  });

  closeSettingsBtn.addEventListener('click', () => {
    settingsModal.classList.add('hidden');
  });

  cancelSettingsBtn.addEventListener('click', () => {
    settingsModal.classList.add('hidden');
  });

  saveSettingsBtn.addEventListener('click', async () => {
    const key = geminiKeyInput.value.trim();
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gemini_api_key: key })
      });
      const data = await res.json();
      showToast(data.message || '設定を保存しました');
      settingsModal.classList.add('hidden');
      await loadSettings();
    } catch (err) {
      console.error(err);
      showToast('設定の保存に失敗しました');
    }
  });
}

// 統計情報読み込み
async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    statArticlesEl.textContent = `蓄積記事: ${data.total_articles.toLocaleString()} 件`;
    statDaysEl.textContent = `アーカイブ: ${data.total_days} 日分`;
    if (data.last_updated) {
      const d = new Date(data.last_updated);
      statUpdatedEl.textContent = `最終更新: ${d.toLocaleDateString('ja-JP')} ${d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })}`;
    }
  } catch (err) {
    console.error('統計読み込みエラー:', err);
  }
}

// 日付一覧読み込み
async function loadDates() {
  try {
    const res = await fetch('/api/dates');
    const data = await res.json();
    availableDates = data.dates || [];

    dateListEl.innerHTML = '';
    if (availableDates.length === 0) {
      dateListEl.innerHTML = '<div class="p-3 text-center text-xs text-slate-400">記事がまだありません。<br>上の「最新ニュース取得」を押してください。</div>';
      return;
    }

    availableDates.forEach((item, index) => {
      const btn = document.createElement('button');
      btn.className = `date-item w-full flex items-center justify-between px-3 py-2 text-xs rounded-xl border border-transparent hover:bg-slate-100 transition-all text-left ${item.article_date === currentDate || (!currentDate && index === 0) ? 'active' : 'text-slate-700'}`;
      
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

    // 初期選択日付の設定
    if (!currentDate && availableDates.length > 0) {
      currentDate = availableDates[0].article_date;
      datePickerInput.value = currentDate;
      await loadArticles();
    }
  } catch (err) {
    console.error('日付取得エラー:', err);
  }
}

// 日付の選択
function selectDate(dateStr) {
  currentDate = dateStr;
  datePickerInput.value = dateStr;

  // 日付リストのアクティブ表示更新
  document.querySelectorAll('.date-item').forEach(el => {
    el.classList.remove('active');
  });
  const match = [...document.querySelectorAll('.date-item')].find(el => el.textContent.includes(formatDisplayDate(dateStr)));
  if (match) match.classList.add('active');

  loadArticles();
}

// 記事一覧の読み込み
async function loadArticles() {
  articlesContainerEl.innerHTML = `
    <div class="p-12 text-center text-slate-400 text-xs bg-white rounded-2xl border border-slate-200 flex flex-col items-center justify-center gap-2">
      <div class="w-6 h-6 border-2 border-orange-500 border-t-transparent rounded-full animate-spin"></div>
      <span>記事を読み込み中...</span>
    </div>
  `;

  try {
    let url = `/api/articles?date=${encodeURIComponent(currentDate || '')}`;
    if (currentCategory && currentCategory !== 'all') {
      url += `&category=${encodeURIComponent(currentCategory)}`;
    }
    if (searchQuery) {
      url += `&q=${encodeURIComponent(searchQuery)}`;
    }

    const res = await fetch(url);
    const data = await res.json();
    const articles = data.articles || [];

    // ヘッダー情報更新
    currentDisplayDateEl.textContent = currentDate ? `${formatDisplayDate(currentDate)} のニュース` : 'ニュース一覧';
    currentCountBadgeEl.textContent = `${articles.length} 件`;

    if (articles.length === 0) {
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

    // 記事カードのレンダリング
    articlesContainerEl.innerHTML = articles.map(renderArticleCard).join('');
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

// 記事カード1枚のHTML生成
function renderArticleCard(a) {
  const catClass = categoryBadgeClasses[a.category] || categoryBadgeClasses['地域・一般'];
  
  // 要約テキストの箇条書き整形
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

  return `
    <article class="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-sm hover:shadow-md transition-all space-y-4">
      
      <!-- 上部メタ情報 -->
      <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div class="flex items-center gap-2">
          <span class="px-2.5 py-0.5 rounded-full border text-[11px] font-semibold ${catClass}">
            ${escapeHtml(a.category)}
          </span>
          <span class="font-medium text-slate-600 flex items-center gap-1">
            <i data-lucide="newspaper" class="w-3 h-3 text-slate-400"></i>
            ${escapeHtml(a.source || '配信元')}
          </span>
        </div>
        <span class="text-slate-400 text-[11px] flex items-center gap-1">
          <i data-lucide="clock" class="w-3 h-3"></i>
          ${escapeHtml(a.published_at || '')}
        </span>
      </div>

      <!-- 記事タイトル -->
      <h3 class="text-base sm:text-lg font-bold text-slate-900 leading-snug">
        ${escapeHtml(a.title)}
      </h3>

      <!-- 30秒要約ボックス -->
      <div class="summary-box p-3.5 rounded-xl space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-xs font-bold text-orange-950 flex items-center gap-1.5">
            <i data-lucide="zap" class="w-3.5 h-3.5 text-orange-600 fill-orange-500"></i>
            さっと読める要約ポイント
          </span>
          ${isAi ? `
            <span class="text-[10px] font-semibold px-2 py-0.5 bg-gradient-to-r from-purple-100 to-indigo-100 text-indigo-700 rounded-full border border-indigo-200 flex items-center gap-1">
              ✨ AI要約
            </span>
          ` : `
            <span class="text-[10px] text-slate-400">自動抽出</span>
          `}
        </div>
        <ul class="space-y-1.5 pl-1">
          ${summaryHtml}
        </ul>
      </div>

      <!-- 下部アクション: 元記事リンク -->
      <div class="flex items-center justify-between pt-1">
        <div class="text-[11px] text-slate-400">
          詳細や写真・続報は元記事で確認できます
        </div>
        <a 
          href="${escapeHtml(a.url)}" 
          target="_blank" 
          rel="noopener noreferrer" 
          class="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-slate-900 hover:bg-orange-600 text-white transition-all shadow-sm"
        >
          <span>元記事を読む</span>
          <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
        </a>
      </div>

    </article>
  `;
}

// 設定状態読み込み
async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    const data = await res.json();
    if (data.has_gemini_key) {
      apiKeyStatusEl.innerHTML = `
        <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
        <span class="text-emerald-700 font-medium">登録済み (末尾: ${data.key_hint}) - 高精度AI要約モード有効</span>
      `;
    } else {
      apiKeyStatusEl.innerHTML = `
        <span class="w-2 h-2 rounded-full bg-slate-400"></span>
        <span>未登録（標準自動要約モードで稼働中・完全無料）</span>
      `;
    }
  } catch (err) {
    console.error('設定取得エラー:', err);
  }
}

// トースト通知表示
function showToast(msg) {
  toastMsgEl.textContent = msg;
  toastEl.classList.remove('translate-y-20', 'opacity-0');
  toastEl.classList.add('translate-y-0', 'opacity-100');
  setTimeout(() => {
    toastEl.classList.remove('translate-y-0', 'opacity-100');
    toastEl.classList.add('translate-y-20', 'opacity-0');
  }, 3500);
}

// 日付フォーマット関数 (YYYY-MM-DD -> YYYY年M月D日)
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

// HTMLエスケープ
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
