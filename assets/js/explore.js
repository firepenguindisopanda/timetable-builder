/*
   Timetable explorer, client behaviour.

   Two jobs:

   1. Render the provenance timestamps in the reader's own timezone and as
      relative ages, so "checked 3 hours ago" stays true on a cached page.
   2. Search and filter the course index entirely in the browser. The whole
      index is one request, so typing costs nothing after that.

   Filter state is mirrored into the query string, which makes a filtered
   view something a student can send to someone else.
*/

(function () {
  'use strict';

  var DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
              'Friday', 'Saturday', 'Sunday'];
  var TOTAL_WEEKS = 12;
  var PAGE_SIZE = 50;

  // time

  function formatAbsolute(date) {
    return date.toLocaleString(undefined, {
      day: 'numeric', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  }

  function formatRelative(date) {
    var seconds = (date.getTime() - Date.now()) / 1000;
    var units = [
      ['year', 31536000], ['month', 2592000], ['week', 604800],
      ['day', 86400], ['hour', 3600], ['minute', 60]
    ];
    if (!window.Intl || !Intl.RelativeTimeFormat) {
      return formatAbsolute(date);
    }
    var rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
    for (var i = 0; i < units.length; i++) {
      var amount = seconds / units[i][1];
      if (Math.abs(amount) >= 1) {
        return rtf.format(Math.round(amount), units[i][0]);
      }
    }
    return rtf.format(Math.round(seconds), 'second');
  }

  function renderTimestamps() {
    var nodes = document.querySelectorAll('time[data-ts]');
    Array.prototype.forEach.call(nodes, function (node) {
      var date = new Date(node.getAttribute('data-ts'));
      if (isNaN(date.getTime())) { return; }
      node.setAttribute('datetime', date.toISOString());
      node.setAttribute('title', formatAbsolute(date));
      node.textContent = node.getAttribute('data-format') === 'rel'
        ? formatRelative(date)
        : formatAbsolute(date);
    });
  }

  // helpers

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function weekMeter(mask) {
    var out = '<span class="wk wk--sm" role="img" aria-label="'
            + escapeHtml(weekLabel(mask)) + '">';
    for (var w = 1; w <= TOTAL_WEEKS; w++) {
      out += (mask >> (w - 1)) & 1 ? '<i class="on"></i>' : '<i></i>';
    }
    return out + '</span>';
  }

  function weekLabel(mask) {
    var weeks = [];
    for (var w = 1; w <= TOTAL_WEEKS; w++) {
      if ((mask >> (w - 1)) & 1) { weeks.push(w); }
    }
    if (!weeks.length) { return 'No teaching weeks recorded'; }
    return 'Runs in week' + (weeks.length > 1 ? 's ' : ' ') + weeks.join(', ');
  }

  // static list filtering

  // The rooms and lecturers pages are server-rendered and short enough to
  // filter in the DOM, so they need no payload of their own.
  function wireStaticFilter() {
    var input = document.getElementById('listFilter');
    var list = document.getElementById('list');
    var count = document.getElementById('listCount');
    if (!input || !list) { return; }

    var items = Array.prototype.slice.call(list.children);
    var noun = list.getAttribute('aria-label').toLowerCase();

    function run() {
      var term = input.value.trim().toLowerCase();
      var visible = 0;
      items.forEach(function (item) {
        var hit = !term || item.getAttribute('data-search').indexOf(term) !== -1;
        item.hidden = !hit;
        if (hit) { visible++; }
      });
      count.textContent = term
        ? visible.toLocaleString() + ' of ' + items.length.toLocaleString() + ' ' + noun
        : items.length.toLocaleString() + ' ' + noun;
    }

    input.addEventListener('input', run);
    run();
  }

  // state

  // Column-header tooltips show on hover and on focus. Focus is what makes
  // them reachable by keyboard and by tap, so Escape has to close them again.
  function wireTooltipDismiss() {
    document.addEventListener('keydown', function (event) {
      var active = document.activeElement;
      if (event.key === 'Escape' && active &&
          active.classList.contains('th-help-trigger')) {
        active.blur();
      }
    });
  }

  var page = document.getElementById('results');
  if (!page) {
    renderTimestamps();
    wireStaticFilter();
    wireTooltipDismiss();
    return;
  }

  var courses = [];
  var matches = [];
  var shown = 0;

  var state = { q: '', faculty: '', day: '', type: '', weeks: [], slot: null };

  var els = {
    q: document.getElementById('q'),
    qClear: document.getElementById('qClear'),
    faculty: document.getElementById('fFaculty'),
    day: document.getElementById('fDay'),
    type: document.getElementById('fType'),
    weekPick: document.getElementById('weekPick'),
    reset: document.getElementById('reset'),
    count: document.getElementById('count'),
    more: document.getElementById('more'),
    moreBtn: document.getElementById('moreBtn'),
    results: page
  };

  // filtering

  function haystack(course) {
    if (course._hay === undefined) {
      course._hay = [
        course.code,
        course.code.replace(/\s+/g, ''),
        course.title,
        course.department,
        course.faculty,
        (course.rooms || []).join(' '),
        (course.staff || []).join(' ')
      ].join(' ').toLowerCase();
    }
    return course._hay;
  }

  function matchesState(course) {
    if (state.faculty && course.faculty !== state.faculty) { return false; }
    if (state.day && (course.days || []).indexOf(state.day) === -1) { return false; }
    if (state.type && (course.types || []).indexOf(state.type) === -1) { return false; }

    if (state.weeks.length) {
      var wanted = 0;
      for (var i = 0; i < state.weeks.length; i++) {
        wanted |= 1 << (state.weeks[i] - 1);
      }
      // A course qualifies if it runs in any of the selected weeks.
      if (!(course.weeks & wanted)) { return false; }
    }

    if (state.slot !== null && (course.slots || []).indexOf(state.slot) === -1) {
      return false;
    }

    if (state.q) {
      var terms = state.q.toLowerCase().split(/\s+/).filter(Boolean);
      var hay = haystack(course);
      for (var t = 0; t < terms.length; t++) {
        if (hay.indexOf(terms[t]) === -1) { return false; }
      }
    }
    return true;
  }

  // rendering

  function rowHtml(course) {
    var days = (course.days || []).map(function (d) { return d.slice(0, 3); });
    var meta = [course.faculty, course.department].filter(Boolean).join(' · ');

    return '<li><a class="row" href="/explore/course/'
      + encodeURIComponent(course.code) + '">'
      + '<div>'
        + '<div class="row-code">' + escapeHtml(course.code) + '</div>'
        + weekMeter(course.weeks)
      + '</div>'
      + '<div>'
        + '<div class="row-title">' + escapeHtml(course.title || 'Untitled course') + '</div>'
        + '<div class="row-meta">' + escapeHtml(meta || 'Department not published') + '</div>'
      + '</div>'
      + '<div class="row-right">'
        + '<span class="row-n">' + course.sessions + ' class'
        + (course.sessions === 1 ? '' : 'es') + '</span>'
        + '<span class="row-days">' + escapeHtml(days.join(' ')) + '</span>'
      + '</div>'
      + '</a></li>';
  }

  function renderPage(reset) {
    if (reset) {
      els.results.innerHTML = '';
      shown = 0;
    }
    var slice = matches.slice(shown, shown + PAGE_SIZE);
    var html = '';
    for (var i = 0; i < slice.length; i++) { html += rowHtml(slice[i]); }
    els.results.insertAdjacentHTML('beforeend', html);
    shown += slice.length;
    els.more.hidden = shown >= matches.length;
    if (!els.more.hidden) {
      els.moreBtn.textContent = 'Show more courses ('
        + (matches.length - shown) + ' left)';
    }
  }

  function describeFilters() {
    var bits = [];
    if (state.slot !== null) {
      var day = DAYS[Math.floor(state.slot / 24)];
      var hour = state.slot % 24;
      bits.push(day + ' ' + (hour < 10 ? '0' : '') + hour + ':00');
    } else if (state.day) {
      bits.push(state.day);
    }
    if (state.weeks.length) {
      bits.push('week' + (state.weeks.length > 1 ? 's ' : ' ') + state.weeks.join(', '));
    }
    return bits.length ? ' in ' + bits.join(', ') : '';
  }

  function apply(resetPaging) {
    matches = courses.filter(matchesState);
    els.count.textContent = matches.length === courses.length
      ? courses.length.toLocaleString() + ' courses'
      : matches.length.toLocaleString() + ' of '
        + courses.length.toLocaleString() + ' courses' + describeFilters();

    if (!matches.length) {
      els.results.innerHTML =
        '<li><div class="empty"><h2>No courses match</h2>'
        + '<p>Try a shorter search, or clear a filter.</p></div></li>';
      els.more.hidden = true;
      shown = 0;
    } else {
      renderPage(resetPaging !== false);
    }
    syncUrl();
  }

  // url

  function syncUrl() {
    var params = new URLSearchParams();
    if (state.q) { params.set('q', state.q); }
    if (state.faculty) { params.set('faculty', state.faculty); }
    if (state.day) { params.set('day', state.day); }
    if (state.type) { params.set('type', state.type); }
    if (state.weeks.length) { params.set('week', state.weeks.join(',')); }
    if (state.slot !== null) { params.set('slot', state.slot); }
    var query = params.toString();
    history.replaceState(null, '', query ? '?' + query : location.pathname);
  }

  function readUrl() {
    var params = new URLSearchParams(location.search);
    state.q = params.get('q') || '';
    state.faculty = params.get('faculty') || '';
    state.day = params.get('day') || '';
    state.type = params.get('type') || '';
    state.slot = params.has('slot') ? parseInt(params.get('slot'), 10) : null;
    state.weeks = (params.get('week') || '').split(',')
      .map(function (w) { return parseInt(w, 10); })
      .filter(function (w) { return w >= 1 && w <= TOTAL_WEEKS; });

    els.q.value = state.q;
    els.qClear.hidden = !state.q;
    els.faculty.value = state.faculty;
    els.day.value = state.day;
    els.type.value = state.type;
    paintWeekButtons();
    paintHeatCells();
  }

  function paintWeekButtons() {
    var buttons = els.weekPick.querySelectorAll('button');
    Array.prototype.forEach.call(buttons, function (button) {
      var week = parseInt(button.getAttribute('data-week'), 10);
      button.setAttribute('aria-pressed',
        state.weeks.indexOf(week) !== -1 ? 'true' : 'false');
    });
  }

  function paintHeatCells() {
    var cells = document.querySelectorAll('.heat-cell');
    Array.prototype.forEach.call(cells, function (cell) {
      var slot = DAYS.indexOf(cell.getAttribute('data-day')) * 24
               + parseInt(cell.getAttribute('data-hour'), 10);
      cell.setAttribute('aria-pressed', state.slot === slot ? 'true' : 'false');
    });
  }

  // events

  function debounce(fn, wait) {
    var timer;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, wait);
    };
  }

  var applySoon = debounce(function () { apply(true); }, 120);

  els.q.addEventListener('input', function () {
    state.q = els.q.value.trim();
    els.qClear.hidden = !state.q;
    applySoon();
  });

  els.qClear.addEventListener('click', function () {
    state.q = '';
    els.q.value = '';
    els.qClear.hidden = true;
    els.q.focus();
    apply(true);
  });

  ['faculty', 'day', 'type'].forEach(function (key) {
    els[key].addEventListener('change', function () {
      state[key] = els[key].value;
      // Choosing a day on its own drops the more specific slot filter.
      if (key === 'day') { state.slot = null; paintHeatCells(); }
      apply(true);
    });
  });

  els.weekPick.addEventListener('click', function (event) {
    var button = event.target.closest('button[data-week]');
    if (!button) { return; }
    var week = parseInt(button.getAttribute('data-week'), 10);
    var at = state.weeks.indexOf(week);
    if (at === -1) { state.weeks.push(week); } else { state.weeks.splice(at, 1); }
    state.weeks.sort(function (a, b) { return a - b; });
    paintWeekButtons();
    apply(true);
  });

  document.addEventListener('click', function (event) {
    var cell = event.target.closest('.heat-cell');
    if (!cell) { return; }
    var slot = DAYS.indexOf(cell.getAttribute('data-day')) * 24
             + parseInt(cell.getAttribute('data-hour'), 10);
    // Clicking the active slot clears it, so the grid toggles.
    state.slot = state.slot === slot ? null : slot;
    state.day = '';
    els.day.value = '';
    paintHeatCells();
    apply(true);
    els.results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  els.reset.addEventListener('click', function () {
    state = { q: '', faculty: '', day: '', type: '', weeks: [], slot: null };
    els.q.value = '';
    els.qClear.hidden = true;
    els.faculty.value = '';
    els.day.value = '';
    els.type.value = '';
    paintWeekButtons();
    paintHeatCells();
    apply(true);
  });

  els.moreBtn.addEventListener('click', function () { renderPage(false); });

  // boot

  renderTimestamps();
  wireTooltipDismiss();
  els.count.textContent = 'Loading courses…';

  fetch('/explore/courses.json')
    .then(function (response) {
      if (!response.ok) { throw new Error('HTTP ' + response.status); }
      return response.json();
    })
    .then(function (data) {
      courses = data.courses || [];
      readUrl();
      apply(true);
    })
    .catch(function (error) {
      els.count.textContent = '';
      els.results.innerHTML =
        '<li><div class="empty"><h2>Course list did not load</h2>'
        + '<p>' + escapeHtml(error.message)
        + '. Reload the page, or open a course directly at '
        + '/explore/course/&lt;code&gt;.</p></div></li>';
    });
})();
