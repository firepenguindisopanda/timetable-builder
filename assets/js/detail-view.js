'use strict';

/**
 * One class, in full, as markup.
 *
 * The same body is shown in two places: the panel beside the event list, and
 * a dialog that opens when a block on the grid is tapped. Building it here
 * once means the two can never drift apart, and means what each field says
 * is tested rather than assembled ad hoc in the page.
 *
 * Everything is decided by the caller and passed in through the model; this
 * file adds no rules of its own. The page owns the surrounding panel or
 * overlay and the click wiring.
 */

/** Escape for HTML text and double-quoted attributes, DOM-free. */
function escapeDetail(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** The four block colours, reused so the dialog matches the grid. */
function _detailTypeClass(type) {
  const known = ['lecture', 'lab', 'tutorial'];
  const lower = String(type || '').toLowerCase();
  return known.includes(lower) ? lower : 'other';
}

function _detailTypeIcon(type) {
  const icons = {
    'Lecture': 'bi-easel',
    'Lab': 'bi-cpu',
    'Tutorial': 'bi-chat-dots',
    'Seminar': 'bi-people',
    'Workshop': 'bi-tools',
  };
  return icons[type] || 'bi-calendar-event';
}

function _detailTime12(time24) {
  if (!time24) return '';
  return timeLabel(timeToMins(time24));
}

/** Empty fields say "Not published", never nothing at all (E9). */
function _detailField(label, value) {
  const isEmpty = value === null || value === undefined || value === '';
  const shown = isEmpty ? 'Not published' : value;
  return `<div class="detail-field">
      <span class="detail-field-label">${escapeDetail(label)}</span>
      <span class="detail-field-value${isEmpty ? ' empty' : ''}">${escapeDetail(String(shown))}</span>
    </div>`;
}

/**
 * Uploaded PDFs carry the printed week text and nothing else, so there is no
 * expanded array to count. Saying "Not published" for those would be a lie:
 * the weeks are right there, just not as data.
 */
function describeDetailWeeks(details) {
  if (details.weeksRaw) {
    const count = details.weeks ? ` (${details.weeks.length} weeks)` : '';
    return details.weeksRaw + count;
  }
  if (details.weeks && details.weeks.length) {
    return 'W' + details.weeks.join(', W');
  }
  return '';
}

/**
 * How the grouping rules read this course's classes, and how to disagree.
 *
 * No rule gets all 457 ambiguous course-and-type groups in the warehouse
 * right, so the correction is part of the design rather than an escape
 * hatch. Section 4 of the spec calls for it explicitly.
 */
const DETAIL_GROUP_REASON = {
  sittings: 'This runs more than once a week and you attend one sitting. ' +
            'Drag it to pick a different one.',
  single: 'Only one sitting of this is published.',
  overlap: 'These run at the same time, so you can only be at one.',
  split: 'You said this course runs more than one of these a week.',
};

function _groupOverrideHtml(details) {
  const isMenu = details.optionCount > 1;

  // Splitting is the rare correction: a course that really does run two
  // different lectures a week rather than the same one twice.
  const split = details.groupReason === 'split' || details.groupReason === 'overlap';
  const control = split
    ? `<button type="button" class="btn btn-outline-secondary btn-sm group-reset"
            data-course-key="${escapeDetail(details.courseKey)}"
            data-type="${escapeDetail(details.type || '')}">
            Go back to picking one
       </button>`
    : (isMenu
        ? `<button type="button" class="btn btn-outline-secondary btn-sm group-split"
                data-course-key="${escapeDetail(details.courseKey)}"
                data-type="${escapeDetail(details.type || '')}">
                I attend more than one of these a week
           </button>`
        : '');
  if (!control) return '';

  return `<div class="group-override">
      <span class="why">${escapeDetail(DETAIL_GROUP_REASON[details.groupReason] || '')}</span>
      ${control}
    </div>`;
}

/**
 * Every sitting of the open class, each with what can be done to it.
 *
 * One of each type is what auto-placement builds, but it is a guide, not a
 * rule the student is held to: their real week may include two sittings of
 * the same lab, or none. Adding and removing individual sittings is how the
 * timetable stops arguing with them about it.
 */
function _sittingsSectionHtml(details, sessions, attendedIds) {
  if (!sessions.length) return '';
  const attended = new Set(attendedIds);

  const rows = sessionsInTimetableOrder(sessions).map(session => {
    const when = `${session.day.slice(0, 3)} ${session.startTime}-${session.endTime}`;
    const where = [session.streamLabel, session.room].filter(Boolean).join(' · ');
    const isViewing = session.sessionId === details.sessionId;
    const isAttended = attended.has(session.sessionId);

    let tail;
    if (isViewing) {
      tail = '<span class="sitting-state">This one</span>';
    } else if (isAttended) {
      tail = `<button type="button" class="btn btn-outline-secondary btn-sm sitting-remove"
          data-group-id="${escapeDetail(details.groupId)}"
          data-session-id="${escapeDetail(String(session.sessionId))}">Remove</button>`;
    } else {
      tail = `<button type="button" class="btn btn-outline-secondary btn-sm sitting-add"
          data-group-id="${escapeDetail(details.groupId)}"
          data-session-id="${escapeDetail(String(session.sessionId))}">Also attend</button>`;
    }

    return `<div class="sitting-row${isViewing ? ' viewing' : ''}">
        <span class="sitting-when">${escapeDetail(when)}</span>
        <span class="sitting-where">${escapeDetail(where)}</span>
        ${tail}
      </div>`;
  });

  const hint = sessions.length > 1
    ? 'Drag the block on the grid to swap this sitting for another.'
    : 'Only one sitting of this is published.';

  return `<div class="detail-section">
      <h4 class="detail-section-title"><i class="bi bi-collection"></i>
          Sittings (${sessions.length})</h4>
      <div class="sittings-list">${rows.join('')}</div>
      <div class="detail-field" style="padding-top: 8px;">
          <span class="detail-field-value empty">${escapeDetail(hint)}</span>
      </div>
    </div>`;
}

function _rawDataText(details) {
  const fields = [
    ['courseKey', details.courseKey],
    ['courseTitle', details.courseTitle],
    ['origin', details.origin],
    ['type', details.type],
    ['groupId', details.groupId],
    ['groupReason', details.groupReason],
    ['optionCount', details.optionCount],
    ['pinned', details.pinned],
    ['sessionId', details.sessionId],
    ['streamId', details.streamId],
    ['day', details.day],
    ['startTime', details.startTime],
    ['endTime', details.endTime],
    ['room', details.room],
    ['staff', (details.staff || []).join(', ')],
    ['streamLabel', details.streamLabel],
    ['weeks', details.weeks ? details.weeks.join(', ') : null],
    ['weeksRaw', details.weeksRaw],
    ['sourceCount', details.sourceCount],
    ['sourceFile', details.sourceFile],
  ];
  return fields
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${k}: ${v}`)
    .join('\n');
}

/**
 * The full detail body for one placed class.
 *
 * `model` carries:
 * - `details`: what `getPlacedEventDetails` returns.
 * - `sessions`: every sitting of the class's group.
 * - `attendedSessionIds`: the sittings the group's placements show.
 * - `clashing`: whether this placement is in a genuine clash, which adds the
 *   way into the resolve dialog.
 * - `idSuffix`: keeps the raw-data region's id unique when the panel and the
 *   dialog both hold a copy of this markup at once.
 */
function renderEventDetail(model) {
  const details = model.details;
  const typeClass = _detailTypeClass(details.type);
  const typeIcon = _detailTypeIcon(details.type);
  const rawId = 'rawDataContent' + (model.idSuffix || '');

  let html = '';

  html += `<div class="detail-header">
      <h3 class="detail-course-title">${escapeDetail(details.courseTitle)}</h3>
      <span class="detail-type-badge ${typeClass}">
          <i class="bi ${typeIcon}"></i>
          ${escapeDetail(details.type || 'Class')}${details.streamLabel ? ' ' + escapeDetail(details.streamLabel) : ''}
      </span>
    </div>`;

  html += `<div class="detail-section">
      <h4 class="detail-section-title"><i class="bi bi-clock"></i> Schedule</h4>
      ${_detailField('Day', details.day)}
      ${_detailField('Start Time', _detailTime12(details.startTime))}
      ${_detailField('End Time', _detailTime12(details.endTime))}
      ${_detailField('Weeks', describeDetailWeeks(details))}
    </div>`;

  html += `<div class="detail-section">
      <h4 class="detail-section-title"><i class="bi bi-geo-alt"></i> Location</h4>
      ${_detailField('Room', details.room)}
    </div>`;

  html += `<div class="detail-section">
      <h4 class="detail-section-title"><i class="bi bi-person"></i> People</h4>
      ${_detailField('Staff', (details.staff || []).join(', '))}
    </div>`;

  html += `<div class="detail-section">
      <h4 class="detail-section-title"><i class="bi bi-info-circle"></i> This class</h4>
      ${_detailField('Course', details.courseKey)}
      ${_detailField('Chosen by', details.pinned ? 'You' : 'Auto-placement')}
      ${_detailField('Source', details.origin === 'upload'
          ? 'Your upload: ' + (details.sourceFile || 'PDF')
          : 'Published timetable')}
      ${_groupOverrideHtml(details)}
    </div>`;

  html += _sittingsSectionHtml(details, model.sessions || [],
      model.attendedSessionIds || []);

  // The clash's own shortcut sits with the actions: a student who opened
  // this class because it is ringed red should not have to go find the
  // conflicts panel to act on it.
  const resolveButton = model.clashing
    ? `<button type="button" class="btn btn-outline-info btn-sm detail-resolve-clash"
          data-group-id="${escapeDetail(details.groupId)}"
          data-session-id="${escapeDetail(String(details.sessionId))}">
          <i class="bi bi-exclamation-triangle me-1"></i> Resolve the clash
       </button>`
    : '';

  // Two sizes of removal, smallest first. Taking one class off is the
  // everyday act; taking the whole course is the destructive one and keeps
  // the red.
  html += `<div class="detail-section" style="display: flex; gap: 8px; flex-wrap: wrap;">
      ${resolveButton}
      <button type="button" class="btn btn-outline-secondary btn-sm detail-remove-class"
          data-group-id="${escapeDetail(details.groupId)}"
          data-session-id="${escapeDetail(String(details.sessionId))}">
          <i class="bi bi-x-lg me-1"></i> Remove this class
      </button>
      <button type="button" class="btn btn-outline-danger btn-sm detail-remove-course"
          data-course-key="${escapeDetail(details.courseKey)}">
          <i class="bi bi-trash me-1"></i> Remove ${escapeDetail(details.courseKey)}
      </button>
    </div>`;

  html += `<button type="button" class="detail-raw-toggle"
      aria-expanded="false"
      aria-controls="${rawId}">
      <span><i class="bi bi-chevron-right me-1"></i> Raw Extracted Data</span>
    </button>
    <div id="${rawId}" class="detail-raw-content" role="region">
        <div class="detail-raw-inner">
            <pre>${escapeDetail(_rawDataText(details))}</pre>
        </div>
    </div>`;

  return html;
}
