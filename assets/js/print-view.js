'use strict';

/**
 * The printed page, as markup.
 *
 * Takes what `buildPrintModel` decided and turns it into HTML. It makes no
 * decisions of its own: no filtering, no formatting of times or names, no
 * choosing what is worth showing. If something here needs a rule, the rule
 * belongs in print-model.js where it can be tested against real sessions.
 *
 * Returns a string rather than nodes so it can be tested outside a browser,
 * in the same vm harness as everything else in `assets/js`.
 *
 * See PRINT-EXPORT-SPEC.md section 5.
 */

/**
 * Escape for HTML text and double-quoted attributes.
 *
 * `escapeHtml` in calendar-utils.js round-trips through a real DOM node,
 * which this cannot do: it builds a string, and it is tested in a vm context
 * that has no `document`. It also escapes only what a text node needs, and
 * this writes attributes too.
 */
function escapePrint(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** The swatch treatment that stands for an activity type. */
const FILL_CLASS = Object.freeze({
  lecture: 'pv-fill-solid',
  lab: 'pv-fill-hatch',
  tutorial: 'pv-fill-outline',
  other: 'pv-fill-dots',
});

function fillClass(typeClass) {
  return FILL_CLASS[typeClass] || FILL_CLASS.other;
}

/** The hue for a colour index, wrapping the palette rather than running off it. */
function hueFor(colourIndex) {
  const at = ((colourIndex | 0) % PRINT_PALETTE.length + PRINT_PALETTE.length)
    % PRINT_PALETTE.length;
  return PRINT_PALETTE[at].hex;
}

function swatch(typeClass) {
  return `<span class="pv-swatch ${fillClass(typeClass)}" aria-hidden="true"></span>`;
}

function _pvHeader(meta) {
  const facts = [meta.publication, meta.printedAt ? `Printed ${meta.printedAt}` : null]
    .filter(Boolean)
    .map(escapePrint)
    .join(' &middot; ');

  const counts = `${meta.courseCount} course${meta.courseCount === 1 ? '' : 's'}`
    + ` &middot; ${meta.classCount} class${meta.classCount === 1 ? '' : 'es'}`;

  return `<header class="pv-head">
      <h1 class="pv-title">${escapePrint(meta.title)}</h1>
      ${facts ? `<p class="pv-facts">${facts}</p>` : ''}
      <p class="pv-facts">${counts}</p>
      <p class="pv-note">A typical teaching week. Classes that do not run every
        week say which weeks they run.</p>
    </header>`;
}

/**
 * The courses block, which is also the colour legend.
 *
 * On a list layout every entry already names its course and type in words, so
 * this is not load-bearing. It is what makes the swatches decodable, and it
 * doubles as a checklist against a registration record.
 */
function _pvCourses(courses) {
  if (!courses.length) return '';

  const rows = courses.map(course => {
    const flags = [];
    if (course.stale) flags.push('no longer published');
    if (course.origin === 'upload') flags.push('from upload');
    return `<li class="pv-course" style="--pv-hue: ${hueFor(course.colourIndex)}">
        ${swatch('lecture')}
        <span class="pv-code">${escapePrint(course.courseKey)}</span>
        <span class="pv-course-title">${escapePrint(course.courseTitle)}</span>
        ${flags.length ? `<span class="pv-flag">${escapePrint(flags.join(', '))}</span>` : ''}
      </li>`;
  }).join('');

  // Neutral hue, because this key is about the fill and not about any one
  // course.
  const key = ['lecture', 'lab', 'tutorial', 'other']
    .map(typeClass => `<span class="pv-key-item">${swatch(typeClass)}${
      typeClass.charAt(0).toUpperCase() + typeClass.slice(1)
    }</span>`)
    .join('');

  return `<section class="pv-block pv-courses">
      <h2 class="pv-h2">Courses</h2>
      <ul class="pv-course-list">${rows}</ul>
      <p class="pv-key" style="--pv-hue: #444">${key}</p>
    </section>`;
}

function _pvEntry(entry) {
  const detail = [entry.room, entry.staff]
    .filter(Boolean)
    .map(escapePrint);

  if (entry.weeks) {
    // Emphasised only when the class sits out part of the semester, so that
    // "this one is not like the others" is what catches the eye.
    detail.push(
      entry.weeksRestricted
        ? `<strong class="pv-weeks-odd">${escapePrint(entry.weeks)}</strong>`
        : escapePrint(entry.weeks)
    );
  }

  return `<li class="pv-entry" style="--pv-hue: ${hueFor(entry.colourIndex)}">
      <div class="pv-when">${escapePrint(entry.time)}</div>
      <div class="pv-what">
        <p class="pv-line-main">
          ${swatch(entry.typeClass)}
          <span class="pv-code">${escapePrint(entry.courseKey)}</span>
          <span class="pv-type">${escapePrint(entry.type)}</span>
          ${entry.streamLabel
            ? `<span class="pv-stream">${escapePrint(entry.streamLabel)}</span>`
            : ''}
        </p>
        <p class="pv-line-title">${escapePrint(entry.courseTitle)}</p>
        ${detail.length ? `<p class="pv-line-detail">${detail.join(' &middot; ')}</p>` : ''}
      </div>
    </li>`;
}

function _pvDays(days) {
  if (!days.length) {
    return `<p class="pv-empty">Nothing placed yet.</p>`;
  }
  return days.map(day => `<section class="pv-day">
      <h2 class="pv-day-name">${escapePrint(day.day)}</h2>
      <ol class="pv-entries">${day.entries.map(_pvEntry).join('')}</ol>
    </section>`).join('');
}

/**
 * Overlaps, printed rather than hidden.
 *
 * A student who prints a timetable with an unresolved clash in it has to be
 * told on the paper, or the paper is confidently wrong in the one place it
 * matters.
 */
function _pvClashes(clashes) {
  if (!clashes.length) return '';

  const rows = clashes.map(clash => {
    const when = clash.weeks ? ` &middot; ${escapePrint(clash.weeks)}` : '';
    return `<li class="pv-clash">
        <span class="pv-clash-day">${escapePrint(clash.day)}</span>
        ${escapePrint(clash.courseA)} ${escapePrint(clash.timeA)}
        overlaps
        ${escapePrint(clash.courseB)} ${escapePrint(clash.timeB)}${when}
      </li>`;
  }).join('');

  return `<section class="pv-block pv-clashes">
      <h2 class="pv-h2">Clashes (${clashes.length})</h2>
      <ul class="pv-clash-list">${rows}</ul>
    </section>`;
}

/** Anything the builder could not place, so nothing leaves the page silently. */
function _pvUnplaced(unplaced) {
  if (!unplaced.length) return '';

  const rows = unplaced.map(item => `<li>${escapePrint(item.courseKey)}
      &middot; ${escapePrint(item.type)}</li>`).join('');

  return `<section class="pv-block pv-unplaced">
      <h2 class="pv-h2">Not placed (${unplaced.length})</h2>
      <p class="pv-note">These are on your timetable but have no time on this
        page. Open the calendar to place them.</p>
      <ul class="pv-unplaced-list">${rows}</ul>
    </section>`;
}

function renderPrintView(model) {
  if (!model || !model.meta) return '';

  return `<div class="pv-sheet">
    ${_pvHeader(model.meta)}
    ${_pvCourses(model.courses || [])}
    <div class="pv-schedule">${_pvDays(model.days || [])}</div>
    ${_pvClashes(model.clashes || [])}
    ${_pvUnplaced(model.unplaced || [])}
    <footer class="pv-foot">
      Built from published CELCAT timetables. Not an official document.
      Check with your department before relying on it.
    </footer>
  </div>`;
}
