'use strict';

/**
 * The side-by-side view a clash gets resolved in.
 *
 * The conflicts panel can say "move COMP 1601 to Tuesday 10:00", but a
 * one-line fix hides the decision: which of the two classes should give way,
 * and what its other sittings would run into instead. On the grid itself the
 * two blocks sit on the same hour, so on a phone the one a student wants to
 * move is the one under their finger's other target.
 *
 * So a clash opens as a dialog showing both classes at once, each with every
 * sitting it could move to and what that sitting would collide with. Picking
 * one applies the move and pins it, exactly as dragging there would. This
 * does not replace dragging; it is the same choice made reachable.
 *
 * Model here, DOM in the page. `buildResolveModel` decides everything worth
 * testing; `renderResolveDialog` turns the decisions into markup and adds
 * none of its own.
 */

/** Escape for HTML text and double-quoted attributes, DOM-free. */
function escapeResolve(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Everything the dialog needs to show one clash, decided up front.
 *
 * `conflict` is one entry from `classifyConflicts`. `titleOf` maps a course
 * key to its published title, since events do not carry one.
 *
 * Each side lists every sitting of its group in timetable order, annotated
 * with what choosing it would mean:
 *
 * - `current`: the sitting the clash is happening on.
 * - `alsoAttending`: another placement of the same group already shows this
 *   sitting, so it is not available to move onto.
 * - `colliders`: what the sitting would clash with, as "CODE type" strings,
 *   scored against everything placed except the class being moved. Empty
 *   means picking it clears this class completely.
 * - `recommended`: the sitting the classifier's own fix would pick, so the
 *   dialog can agree with the panel instead of contradicting it.
 */
function buildResolveModel(conflict, placements, index, titleOf) {
  const events = eventsFor(placements, index);

  const sides = [conflict.a, conflict.b].map(side => {
    const group = index.get(side.groupId);
    const sessions = group ? sessionsInTimetableOrder(group.sessions) : [];
    const placedHere = new Set(
      placements
        .filter(p => p.groupId === side.groupId)
        .map(p => p.selectedSessionId)
    );
    const pinned = placements.some(p =>
      p.groupId === side.groupId
      && p.selectedSessionId === side.sessionId
      && p.pinned
    );

    const options = sessions.map(session => {
      const candidate = {
        courseKey: side.courseKey,
        groupId: side.groupId,
        day: session.day,
        startTime: session.startTime,
        endTime: session.endTime,
        weeks: session.weeks,
      };
      const colliders = [];
      for (const placed of events) {
        // The class being moved does not collide with itself.
        if (placed.groupId === side.groupId
            && placed.sessionId === side.sessionId) continue;
        if (!eventsCollide(candidate, placed)) continue;
        const label = placed.courseKey
          + (placed.type ? ' ' + String(placed.type).toLowerCase() : '');
        if (!colliders.includes(label)) colliders.push(label);
      }
      return {
        sessionId: session.sessionId,
        day: session.day,
        startTime: session.startTime,
        endTime: session.endTime,
        room: session.room || null,
        streamLabel: session.streamLabel || null,
        weeksRaw: session.weeksRaw || null,
        current: session.sessionId === side.sessionId,
        alsoAttending: session.sessionId !== side.sessionId
          && placedHere.has(session.sessionId),
        colliders,
        recommended: Boolean(
          conflict.fix
          && conflict.fix.groupId === side.groupId
          && conflict.fix.fromSessionId === side.sessionId
          && conflict.fix.sessionId === session.sessionId
        ),
      };
    });

    return {
      groupId: side.groupId,
      courseKey: side.courseKey,
      title: (titleOf && titleOf(side.courseKey)) || null,
      type: side.type || null,
      fromSessionId: side.sessionId,
      pinned,
      options,
    };
  });

  return {
    day: conflict.day,
    timeA: conflict.timeA,
    timeB: conflict.timeB,
    // Null when neither side publishes weeks, which reads as "every week".
    weeks: conflict.weeks,
    sides,
  };
}

/** The four block colours, reused so the dialog matches the grid. */
function _resolveTypeClass(type) {
  const known = ['lecture', 'lab', 'tutorial'];
  const lower = String(type || '').toLowerCase();
  return known.includes(lower) ? lower : 'other';
}

function _optionNote(option) {
  if (option.current) return { text: 'Where it is now', cls: 'now' };
  if (option.alsoAttending) return { text: 'Already on your timetable', cls: 'dim' };
  if (!option.colliders.length) return { text: 'No clashes', cls: 'ok' };
  const first = option.colliders[0];
  const more = option.colliders.length - 1;
  return {
    text: 'Clashes with ' + first + (more > 0 ? ` and ${more} more` : ''),
    cls: 'bad',
  };
}

function _optionHtml(side, option) {
  const note = _optionNote(option);
  const label = [
    option.day.slice(0, 3),
    option.startTime + '-' + option.endTime,
  ].join(' ');
  const detail = [option.streamLabel, option.room]
    .filter(Boolean).join(' · ');

  // The current sitting is shown but not offered: it is the thing being
  // moved, and a button that reapplies the status quo reads as a fix that
  // does nothing.
  const inert = option.current || option.alsoAttending;
  const tag = inert ? 'div' : 'button';
  const attrs = inert
    ? `class="resolve-option ${note.cls === 'now' ? 'is-current' : 'is-taken'}"`
    : `type="button" class="resolve-option${option.recommended ? ' is-recommended' : ''}"
        data-group-id="${escapeResolve(side.groupId)}"
        data-session-id="${escapeResolve(String(option.sessionId))}"
        data-from-session-id="${escapeResolve(String(side.fromSessionId))}"`;

  return `<${tag} ${attrs}>
      <span class="ro-when">${escapeResolve(label)}</span>
      ${detail ? `<span class="ro-where">${escapeResolve(detail)}</span>` : ''}
      <span class="ro-note ${note.cls}">${escapeResolve(note.text)}
        ${option.recommended ? '<em>Suggested</em>' : ''}</span>
    </${tag}>`;
}

function _sideHtml(side) {
  const typeClass = _resolveTypeClass(side.type);
  const pinnedNote = side.pinned
    ? '<span class="resolve-pinned" title="You placed this yourself"><i class="bi bi-pin-angle-fill"></i> Pinned</span>'
    : '';
  return `<section class="resolve-side" aria-label="${escapeResolve(side.courseKey)} ${escapeResolve(side.type || '')}">
      <header class="resolve-side-head">
        <span class="event-dot ${typeClass}"></span>
        <span class="resolve-side-code">${escapeResolve(side.courseKey)}</span>
        <span class="resolve-side-type">${escapeResolve(side.type || 'Class')}</span>
        ${pinnedNote}
      </header>
      ${side.title ? `<p class="resolve-side-title">${escapeResolve(side.title)}</p>` : ''}
      <div class="resolve-options">
        ${side.options.map(option => _optionHtml(side, option)).join('')}
      </div>
    </section>`;
}

/**
 * The dialog's inner markup. The page owns the surrounding <dialog> or
 * overlay, its focus handling, and the click wiring.
 */
function renderResolveDialog(model) {
  const when = model.weeks === null
    ? 'every week'
    : model.weeks.length === 1
      ? 'week ' + model.weeks[0]
      : 'weeks ' + model.weeks.join(', ');

  return `<header class="resolve-head">
      <h2 class="resolve-title">Two classes, one slot</h2>
      <p class="resolve-sub">
        ${escapeResolve(model.sides[0].courseKey)} and
        ${escapeResolve(model.sides[1].courseKey)} overlap on
        ${escapeResolve(model.day)}, ${escapeResolve(when)}.
        Pick another sitting for either one, or drag it on the grid later.
      </p>
      <button type="button" class="resolve-close" aria-label="Close without changing anything">
        <i class="bi bi-x-lg"></i>
      </button>
    </header>
    <div class="resolve-sides">
      ${model.sides.map(_sideHtml).join('')}
    </div>`;
}
