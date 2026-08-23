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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
