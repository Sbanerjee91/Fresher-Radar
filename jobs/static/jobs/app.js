(() => {
  const $ = (id) => document.getElementById(id);
  const el = { q: $('q'), loc: $('loc'), tabs: $('sourceTabs'), newOnly: $('newOnly'), search: $('searchBtn'),
    more: $('moreBtn'), saved: $('savedBtn'), savedCount: $('savedCount'), grid: $('grid'), info: $('resultInfo'),
    reset: $('resetBtn'), toast: $('toast') };

  const SAVED_KEY = 'fresherRadar.saved';
  const PAGE = 24;
  let state = { source: '', role: '', city: '', offset: 0, total: 0, savedView: false };
  let controller = null;

  // ---------- saved jobs (kept in this browser only) ----------
  const readSaved = () => { try { return JSON.parse(localStorage.getItem(SAVED_KEY) || '[]'); } catch { return []; } };
  const writeSaved = (list) => { try { localStorage.setItem(SAVED_KEY, JSON.stringify(list)); } catch {} el.savedCount.textContent = list.length; };
  (function adoptOldSaves() { // jobs saved with the previous version of the site
    try {
      const old = localStorage.getItem('savedFresherJobs');
      if (old && !localStorage.getItem(SAVED_KEY)) localStorage.setItem(SAVED_KEY, old);
    } catch {}
  })();

  // ---------- rendering ----------
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u) ? u : '#');
  const hash = (s) => [...String(s)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
  const initials = (name) => (String(name).match(/[A-Za-z0-9]/g) || ['?']).slice(0, 2).join('').toUpperCase();
  const PIN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><path d="M12 22s7-6.2 7-12a7 7 0 1 0-14 0c0 5.8 7 12 7 12z"/><circle cx="12" cy="10" r="2.5"/></svg>';
  const HEART = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-8-5.2-8-11a4.6 4.6 0 0 1 8-3 4.6 4.6 0 0 1 8 3c0 5.8-8 11-8 11z"/></svg>';

  function card(job, i, savedIds) {
    const on = savedIds.has(String(job.id));
    return `<li class="card tone-${hash(job.source) % 5}" style="--i:${i}" data-id="${esc(job.id)}">
      ${job.is_new ? '<span class="new-tag" aria-label="New">NEW</span>' : ''}
      <div class="card-head">
        <span class="logo" aria-hidden="true">${esc(initials(job.company))}</span>
        <span class="badge">${esc(job.source)}</span>
        <span class="date">${esc(job.posted_at)}</span>
      </div>
      <h2>${esc(job.title)}</h2>
      <div class="company">${esc(job.company)}</div>
      <div class="where">${PIN}<span>${esc(job.location)}</span></div>
      <div class="tags">
        ${job.role ? `<span class="tag role" title="${job.ai ? 'Tagged by AI' : 'Tagged by rules'}">${job.ai ? '&#10022; ' : ''}${esc(job.role)}</span>` : ''}
        ${job.city ? `<span class="tag city">${esc(job.city)}</span>` : ''}
      </div>
      <div class="card-actions">
        <a class="apply" href="${esc(safeUrl(job.apply_url))}" target="_blank" rel="noopener noreferrer">Apply now &rarr;</a>
        <button class="save${on ? ' on' : ''}" type="button" aria-pressed="${on}" aria-label="${on ? 'Remove from saved' : 'Save job'}">${HEART}</button>
      </div></li>`;
  }

  function draw(jobs, append) {
    const saved = new Set(readSaved().map((j) => String(j.id)));
    const start = append ? el.grid.children.length : 0;
    const html = jobs.map((j, i) => card(j, Math.min(i, 12), saved)).join('');
    if (append) el.grid.insertAdjacentHTML('beforeend', html);
    else el.grid.innerHTML = html || `<li class="empty"><strong>ズザッ… nothing here</strong><p>${state.savedView ? 'You have not saved any jobs yet.' : 'No jobs match. Try a broader keyword or clear a filter.'}</p></li>`;
    return start + jobs.length;
  }

  function status(shown) {
    if (state.savedView) { el.info.innerHTML = `Your saved jobs: <b>${state.total}</b>`; }
    else { el.info.innerHTML = state.total ? `Showing <b>${shown}</b> of <b>${state.total}</b> jobs` : ''; }
    el.more.hidden = state.savedView || shown >= state.total;
    el.reset.hidden = !(filters().q || filters().loc || filters().source || filters().new || filters().role || filters().city) && !state.savedView;
  }

  // ---------- loading ----------
  const filters = () => ({ q: el.q.value.trim(), loc: el.loc.value.trim(), source: state.source, new: el.newOnly.checked ? '1' : '', role: state.role, city: state.city });

  async function load(append = false) {
    state.savedView = false;
    el.saved.removeAttribute('data-on');
    if (!append) state.offset = 0;
    controller?.abort();
    controller = new AbortController();
    if (!append) el.grid.innerHTML = Array(6).fill('<li class="skeleton"></li>').join('');
    const params = new URLSearchParams({ ...filters(), offset: state.offset, limit: PAGE });
    try {
      const res = await fetch(`/api/jobs/?${params}`, { signal: controller.signal });
      if (!res.ok) throw new Error(res.status);
      show(await res.json(), append);
    } catch (err) {
      if (err.name === 'AbortError') return;
      el.grid.innerHTML = '<li class="empty"><strong>Connection lost</strong><p>Could not load jobs. Check that the server is running and try again.</p></li>';
    }
  }

  function show(data, append) {
    state.total = data.total_count;
    state.offset = draw(data.jobs, append);
    status(state.offset);
  }

  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const searchSoon = debounce(() => load(), 300);

  // ---------- events ----------
  el.q.addEventListener('input', searchSoon);
  el.loc.addEventListener('input', searchSoon);
  for (const input of [el.q, el.loc]) input.addEventListener('keydown', (e) => { if (e.key === 'Enter') load(); });
  el.search.addEventListener('click', () => load());
  el.more.addEventListener('click', () => load(true));
  el.newOnly.addEventListener('change', () => load());
  el.tabs.addEventListener('change', (e) => { state.source = e.detail.value === 'all' ? '' : e.detail.value; load(); });

  function syncChips() {
    document.querySelectorAll('.chip').forEach((c) => {
      c.classList.toggle('on', c.dataset.role ? c.dataset.role === state.role : c.dataset.city === state.city);
    });
  }
  document.querySelector('main').addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    const key = chip.dataset.role ? 'role' : 'city';
    const value = chip.dataset.role ?? chip.dataset.city;
    state[key] = state[key] === value ? '' : value;
    syncChips();
    load();
  });

  el.reset.addEventListener('click', () => {
    el.q.value = ''; el.loc.value = ''; el.newOnly.checked = false; state.role = ''; state.city = '';
    el.tabs.selected = 0; state.source = '';
    syncChips(); load();
  });

  el.grid.addEventListener('click', (e) => {
    const btn = e.target.closest('.save');
    if (!btn) return;
    const li = btn.closest('.card');
    const id = li.dataset.id;
    let list = readSaved();
    if (list.some((j) => String(j.id) === id)) {
      list = list.filter((j) => String(j.id) !== id);
      el.toast.show('Removed');
    } else {
      list.push({
        id, title: li.querySelector('h2').textContent, company: li.querySelector('.company').textContent,
        location: li.querySelector('.where span').textContent, source: li.querySelector('.badge').textContent,
        apply_url: li.querySelector('.apply').getAttribute('href'), posted_at: li.querySelector('.date').textContent,
        is_new: !!li.querySelector('.new-tag'),
        role: (li.querySelector('.tag.role')?.textContent || '').replace('\u2726', '').trim(),
        city: li.querySelector('.tag.city')?.textContent || '', ai: !!li.querySelector('.tag.role[title*="AI"]'),
      });
      el.toast.show('Saved to list!');
    }
    writeSaved(list);
    const on = list.some((j) => String(j.id) === id);
    btn.classList.toggle('on', on);
    btn.setAttribute('aria-pressed', on);
    btn.setAttribute('aria-label', on ? 'Remove from saved' : 'Save job');
    if (state.savedView) { state.total = list.length; draw(list, false); status(list.length); }
  });

  el.saved.addEventListener('click', () => {
    if (state.savedView) return load();
    controller?.abort();
    state.savedView = true;
    const list = readSaved();
    state.total = list.length;
    draw(list, false);
    status(list.length);
    el.saved.setAttribute('data-on', '');
  });

  // ---------- start-up ----------
  writeSaved(readSaved());
  show(JSON.parse($('initial-data').textContent), false);

  document.querySelectorAll('[data-count]').forEach((n) => { // count-up on the hero numbers
    const to = +n.dataset.count;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches || !to) return;
    const t0 = performance.now();
    const tick = (t) => {
      const p = Math.min((t - t0) / 900, 1);
      n.textContent = Math.round(to * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
})();
