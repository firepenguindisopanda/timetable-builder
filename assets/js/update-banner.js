'use strict';

/*
   The site-wide copy of the explorer's update notice.

   The explorer pages already carry this notice, wired by explore.js. The
   tool pages load neither explore.js nor its page furniture, so this small
   script does the two things the notice needs and nothing else: turn the
   ISO timestamp into the reader's local date, and remember a dismissal.

   The dismissal key is shared with explore.js on purpose, and is keyed on
   the publication id rather than a plain flag: dismissing the notice on any
   page hides it everywhere, and the next republish brings it back.

   localStorage throws rather than returning null in some privacy modes, so
   every access is guarded: a student who cannot save a dismissal should
   still be able to dismiss it for this page view.

   It also dates the freshness rail, which the timetable builder now carries
   too. The rail prints ISO timestamps for the browser to localise, and
   explore.js does that on explorer pages; the builder does not load
   explore.js, so without this its rail read "2026-10-12T22:45:55+00:00".
*/
(function () {
  if (typeof document === 'undefined') { return; }

  var DISMISS_KEY = 'celcat_changes_dismissed';

  function wire() {
    var bar = document.getElementById('updateBar');
    if (!bar) { return; }

    var time = bar.querySelector('time[data-ts]');
    if (time) {
      var date = new Date(time.getAttribute('data-ts'));
      if (!isNaN(date.getTime())) {
        time.setAttribute('datetime', date.toISOString());
        // The same shape explore.js renders, so the notice reads identically
        // wherever it appears.
        time.textContent = date.toLocaleString(undefined, {
          year: 'numeric', month: 'short', day: 'numeric',
          hour: 'numeric', minute: '2-digit',
        });
      }
    }

    var publication = bar.getAttribute('data-publication');
    var dismissed = null;
    try { dismissed = window.localStorage.getItem(DISMISS_KEY); } catch (e) { /* private mode */ }
    if (dismissed && dismissed === publication) {
      bar.hidden = true;
      return;
    }

    var button = document.getElementById('updateDismiss');
    if (!button) { return; }
    button.addEventListener('click', function () {
      bar.hidden = true;
      try { window.localStorage.setItem(DISMISS_KEY, publication); } catch (e) { /* private mode */ }
    });
  }

  // The same two shapes explore.js renders, so the rail reads identically
  // on every page.
  function absolute(date) {
    return date.toLocaleString(undefined, {
      day: 'numeric', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  }

  function relative(date) {
    if (!window.Intl || !Intl.RelativeTimeFormat) { return absolute(date); }
    var seconds = (date.getTime() - Date.now()) / 1000;
    var units = [['year', 31536000], ['month', 2592000], ['week', 604800],
      ['day', 86400], ['hour', 3600], ['minute', 60]];
    var rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
    for (var i = 0; i < units.length; i++) {
      var amount = seconds / units[i][1];
      if (Math.abs(amount) >= 1) { return rtf.format(Math.round(amount), units[i][0]); }
    }
    return rtf.format(Math.round(seconds), 'second');
  }

  function dateRail() {
    var nodes = document.querySelectorAll('.rail time[data-ts]');
    Array.prototype.forEach.call(nodes, function (node) {
      var date = new Date(node.getAttribute('data-ts'));
      if (isNaN(date.getTime())) { return; }
      node.setAttribute('datetime', date.toISOString());
      node.setAttribute('title', absolute(date));
      node.textContent = node.getAttribute('data-format') === 'rel'
        ? relative(date)
        : absolute(date);
    });
  }

  function start() {
    dateRail();
    wire();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
