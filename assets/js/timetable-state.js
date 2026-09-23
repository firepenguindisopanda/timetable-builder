'use strict';

/**
 * The timetable a student is building.
 *
 * Holds the courses they have added, from either source, and which option of
 * each group is currently placed. Everything that decides what a class *is*
 * lives in option-groups.js, and everything that decides *where* it goes lives
 * in placement.js; this file owns identity, history and persistence.
 *
 * The two sources have to converge here. A class picked from the warehouse and
 * the same class read out of a PDF must produce the same stream id, or the
 * student ends up with the course twice.
 */

const STORAGE_KEY_V1 = 'celcat_timetable_data';
const STORAGE_KEY_V2 = 'celcat_timetable_v2';
const STORAGE_KEY_V3 = 'celcat_timetable_v3';

/** How many undo steps are kept. Snapshots are small, but not free. */
const MAX_HISTORY = 50;

function _formatTime(t) {
  if (!t) return '00:00';
  return minsToTime(timeToMins(t));
}

/**
 * A course code as it would be published, or null if the text is not one.
 *
 * CELCAT titles read "COMP 2601, Computer Architecture", so the code is
 * whatever precedes the first comma. The shape test is deliberately strict:
 * mistaking "IENG 3017 LALLA" for a code would key an uploaded course onto
 * something the warehouse never published, and a course that quietly fails to
 * match is better than one that quietly matches the wrong thing.
 *
 * Codes with a parenthetical qualifier are real and kept whole, because UWI
 * publishes "FOUN 1001 (ALJGSB)" and "FOUN 1001 (FULL & PART-TIME)" as
 * different courses.
 */
const COURSE_CODE_SHAPE = /^[A-Z]{2,6} ?\d{2,4}[A-Z]?( \([^()]*\))?$/;

function courseCodeFromTitle(title) {
  if (!title) return null;
  const head = String(title).split(',')[0];
  const cleaned = head.trim().replace(/\s+/g, ' ').toUpperCase();
  return COURSE_CODE_SHAPE.test(cleaned) ? cleaned : null;
}

/** The fallback identity for an upload whose title carries no usable code. */
function titleDerivedKey(title) {
  return String(title || 'Unknown')
    .toUpperCase()
    .replace(/\s+/g, '-')
    .replace(/[^a-zA-Z0-9_-]/g, '');
}

function _session(fields) {
  const startTime = _formatTime(fields.startTime);
  const endTime = _formatTime(fields.endTime);
  const streamId = computeStreamId(
    fields.type,
    fields.day,
    startTime,
    endTime,
    fields.streamLabel
  );
  return {
    // Warehouse rows have a real id. Uploads have none, so the stream id
    // stands in: it is stable for the same class and is what both sources
    // compute identically.
    sessionId: fields.sessionId === undefined || fields.sessionId === null
      ? streamId
      : fields.sessionId,
    streamId,
    type: fields.type || null,
    day: fields.day,
    startTime,
    endTime,
    room: fields.room || null,
    staff: fields.staff || [],
    streamLabel: fields.streamLabel || null,
    weeks: Array.isArray(fields.weeks) ? fields.weeks : null,
    weeksRaw: fields.weeksRaw || null,
    sourceCount: fields.sourceCount || null,
  };
}

class TimetableState {
  constructor(sourceData, savedState) {
    this.sourceData = sourceData || { courses: [] };
    this.sourceData.courses = this.sourceData.courses || [];
    this.publicationId = this.sourceData.publicationId || null;
    // Falls back to the saved copy so a student reloading offline still gets
    // the provenance line on a printed timetable, the same way the courses
    // themselves survive without a network.
    this.publishedAt = this.sourceData.publishedAt
      || (savedState && savedState.publishedAt)
      || null;
    this.overrides = (savedState && savedState.optionGroupOverrides)
      || this.sourceData.optionGroupOverrides
      || {};
    // Courses stay in the pool once loaded even after they are removed from
    // the timetable, so undoing a removal costs no network and a snapshot
    // stays small enough to persist.
    this.courseKeys = (savedState && savedState.courseKeys)
      || this.sourceData.courses.map(c => c.courseKey);
    this.placements = (savedState && savedState.placements) || [];
    // Groups the student emptied on purpose. Auto-placement fills gaps on
    // every load, so without this record a deliberately removed class would
    // quietly come back tomorrow morning.
    this.dismissedGroups = (savedState && savedState.dismissedGroups) || [];
    this.history = (savedState && savedState.history) || [];
    this.future = (savedState && savedState.future) || [];
    this._listeners = [];
    this._groupCache = null;
  }

  // Building state from each source

  /**
   * From `POST /extract`. Upload mode, unchanged in behaviour.
   *
   * Weeks arrive as the printed text ("W1-W12") rather than the expanded array
   * the warehouse holds, so they go to `weeksRaw` and the array stays null.
   * The conflict engine reads a null week array as "every week", which is what
   * keeps an uploaded timetable behaving exactly as it did before the
   * warehouse existed.
   */
  static fromExtractResponse(data) {
    const courses = [];
    const seen = new Set();
    if (!data) return { courses: [] };

    for (const result of (data.results || [])) {
      const title = result.course_title || result.source_file || 'Unknown';
      const code = courseCodeFromTitle(title);
      const courseKey = code || titleDerivedKey(title);
      if (seen.has(courseKey)) continue;
      seen.add(courseKey);

      const sessions = [];
      const seenSessions = new Set();
      for (const entry of (result.entries || [])) {
        const session = _session({
          type: entry.type,
          day: entry.day,
          startTime: entry.start_time,
          endTime: entry.end_time,
          room: entry.room,
          staff: entry.staff ? [entry.staff] : [],
          streamLabel: entry.group_label,
          weeksRaw: entry.weeks,
        });
        if (seenSessions.has(session.streamId)) continue;
        seenSessions.add(session.streamId);
        sessions.push(session);
      }

      courses.push({
        courseKey,
        origin: 'upload',
        code,
        title,
        faculty: null,
        department: null,
        sourceFile: result.source_file || null,
        sessions,
      });
    }
    return { courses };
  }

  /** From `GET /api/timetable/sessions`. */
  static fromWarehouseResponse(data) {
    if (!data) return { courses: [] };
    return {
      publicationId: data.publicationId || null,
      publishedAt: data.publishedAt || null,
      courses: (data.courses || []).map(course => ({
        courseKey: course.code,
        origin: 'warehouse',
        code: course.code,
        title: course.title,
        faculty: course.faculty || null,
        department: course.department || null,
        sourceFile: null,
        sessions: (course.sessions || []).map(_session),
      })),
    };
  }

  // Courses and their option groups

  get activeCourses() {
    const active = new Set(this.courseKeys);
    return this.sourceData.courses.filter(c => active.has(c.courseKey));
  }

  getCourse(courseKey) {
    return this.sourceData.courses.find(c => c.courseKey === courseKey) || null;
  }

  /** Every option group of every course currently on the timetable. */
  get optionGroups() {
    if (this._groupCache === null) {
      this._groupCache = this.activeCourses.flatMap(
        c => deriveOptionGroups(c, this.overrides)
      );
    }
    return this._groupCache;
  }

  get groupIndex() {
    return indexGroups(this.optionGroups);
  }

  getGroup(groupId) {
    return this.optionGroups.find(g => g.groupId === groupId) || null;
  }

  /** The alternatives a placement can be moved between. */
  getOptions(groupId) {
    const group = this.getGroup(groupId);
    return group ? group.sessions : [];
  }

  _invalidate() {
    this._groupCache = null;
  }

  // What is on the grid

  getPlacedEvents() {
    const index = this.groupIndex;
    return this.placements
      .map(placement => {
        const event = eventForPlacement(placement, index);
        if (!event) return null;
        const course = this.getCourse(event.courseKey);
        return {
          ...event,
          courseTitle: (course && course.title) || event.courseKey,
          origin: (course && course.origin) || null,
        };
      })
      .filter(Boolean);
  }

  getPlacedEventDetails(groupId, sessionId) {
    // A group can hold several placements once extra sittings exist, so the
    // session narrows it down. Without one, the first placement is meant.
    const placement = this.placements.find(p =>
      p.groupId === groupId
      && (sessionId === undefined || p.selectedSessionId === sessionId)
    );
    if (!placement) return null;
    const group = this.getGroup(groupId);
    if (!group) return null;
    const session = group.sessions.find(
      s => s.sessionId === placement.selectedSessionId
    );
    if (!session) return null;
    const course = this.getCourse(group.courseKey);

    return {
      groupId,
      courseKey: group.courseKey,
      courseTitle: (course && course.title) || group.courseKey,
      origin: (course && course.origin) || null,
      faculty: course && course.faculty,
      department: course && course.department,
      sourceFile: course && course.sourceFile,
      type: group.type,
      groupReason: group.reason,
      optionCount: group.sessions.length,
      attendedCount: this.placements.filter(p => p.groupId === groupId).length,
      pinned: Boolean(placement.pinned),
      sessionId: session.sessionId,
      streamId: session.streamId,
      day: session.day,
      startTime: session.startTime,
      endTime: session.endTime,
      room: session.room,
      staff: session.staff,
      streamLabel: session.streamLabel,
      weeks: session.weeks,
      weeksRaw: session.weeksRaw,
      sourceCount: session.sourceCount,
    };
  }

  getConflicts() {
    return findConflicts(this.getPlacedEvents());
  }

  /** Conflicts, each saying whether anything can be done about it. */
  getClassifiedConflicts() {
    return classifyConflicts(this.placements, this.groupIndex);
  }

  /**
   * Apply the alternative a conflict suggested.
   *
   * Pins the result, because clicking "Fix" is the student choosing where the
   * class goes just as surely as dragging it there.
   */
  applyFix(fix) {
    if (!fix) return false;
    this.moveEvent(fix.groupId, fix.sessionId, fix.fromSessionId);
    return true;
  }

  // Changing the timetable

  /** Add courses already in the pool, or new ones. Spec 8.1 and 8.2. */
  addCourses(courses) {
    const incoming = (courses || []).filter(
      c => !this.courseKeys.includes(c.courseKey)
    );
    if (incoming.length === 0) {
      return { added: [], alreadyPresent: (courses || []).map(c => c.courseKey) };
    }

    this._snapshot();
    for (const course of incoming) {
      if (!this.getCourse(course.courseKey)) this.sourceData.courses.push(course);
      this.courseKeys.push(course.courseKey);
    }
    this._invalidate();

    const result = placeCourses(
      this.placements,
      incoming.map(c => ({
        courseKey: c.courseKey,
        groups: deriveOptionGroups(c, this.overrides),
      })),
      this.groupIndex
    );
    this.placements = result.placements;
    this._notify();
    return {
      added: incoming.map(c => c.courseKey),
      alreadyPresent: (courses || [])
        .filter(c => !incoming.includes(c))
        .map(c => c.courseKey),
      placed: result.placed,
      summary: result.summary,
    };
  }

  addCourse(course) {
    return this.addCourses([course]);
  }

  /** Remove a course and leave every other placement exactly where it is. */
  removeCourse(courseKey) {
    if (!this.courseKeys.includes(courseKey)) return false;
    this._snapshot();
    this.courseKeys = this.courseKeys.filter(k => k !== courseKey);
    this.placements = this.placements.filter(p => p.courseKey !== courseKey);
    // Group ids start with the course key, so this drops the course's
    // dismissals with it: re-adding the course means wanting all of it back.
    this.dismissedGroups = this.dismissedGroups.filter(
      id => !id.startsWith(courseKey + '|')
    );
    this._invalidate();
    this._notify();
    return true;
  }

  /**
   * Empty the timetable so the student can start again.
   *
   * One snapshot for the whole thing, so it costs a single Ctrl+Z rather than
   * one undo per course. Loaded courses stay in the pool, exactly as
   * `removeCourse` leaves them, which means undoing this does not have to go
   * back to the network for anything.
   *
   * False when there was nothing to clear, so a caller can stay quiet rather
   * than announce that it emptied an empty timetable.
   */
  clearAll() {
    if (!this.courseKeys.length && !this.placements.length) return false;
    this._snapshot();
    this.courseKeys = [];
    this.placements = [];
    this.dismissedGroups = [];
    this._invalidate();
    this._notify();
    return true;
  }

  /**
   * The student chose this option themselves, by dragging or by picking it.
   *
   * Pinning is what makes adding a seventh course safe after they have spent
   * ten minutes arranging the first six.
   */
  moveEvent(groupId, sessionId, fromSessionId) {
    const existing = this.placements.find(p =>
      p.groupId === groupId
      && (fromSessionId === undefined || p.selectedSessionId === fromSessionId)
    );
    // Landing on a session another placement of the group already shows would
    // fold two attended sittings into one block. The drop zones for a drag
    // exclude those, so this only guards the programmatic callers. Dropping a
    // class back on its own slot is not that: it pins where it stands.
    const occupied = this.placements.some(p =>
      p !== existing
      && p.groupId === groupId
      && p.selectedSessionId === sessionId
    );
    if (occupied) return;

    this._snapshot();
    if (existing) {
      this.placements = pinPlacement(
        this.placements, groupId, sessionId, fromSessionId
      );
    } else {
      const group = this.getGroup(groupId);
      if (group) {
        this.dismissedGroups = this.dismissedGroups.filter(id => id !== groupId);
        this.placements = [
          ...this.placements,
          {
            courseKey: group.courseKey,
            groupId,
            selectedSessionId: sessionId,
            pinned: true,
          },
        ];
      }
    }
    this._notify();
  }

  /**
   * Attend an additional sitting of a class that is already on the grid.
   *
   * The one-of-each rule stays what auto-placement builds from, but it is a
   * guide, not a wall: this timetable belongs to the student, and a second
   * sitting they choose to attend is theirs to add. It arrives pinned for the
   * same reason a drag pins: they chose it.
   */
  addSitting(groupId, sessionId) {
    const group = this.getGroup(groupId);
    if (!group) return false;
    if (!group.sessions.some(s => s.sessionId === sessionId)) return false;
    if (this.placements.some(
      p => p.groupId === groupId && p.selectedSessionId === sessionId
    )) return false;

    this._snapshot();
    this.dismissedGroups = this.dismissedGroups.filter(id => id !== groupId);
    this.placements = [
      ...this.placements,
      {
        courseKey: group.courseKey,
        groupId,
        selectedSessionId: sessionId,
        pinned: true,
      },
    ];
    this._notify();
    return true;
  }

  setPinned(groupId, pinned) {
    const placement = this.placements.find(p => p.groupId === groupId);
    if (!placement) return;
    this._snapshot();
    this.placements = this.placements.map(p =>
      p.groupId === groupId ? { ...p, pinned: Boolean(pinned) } : p
    );
    this._notify();
  }

  /**
   * Take one class off the grid without touching the rest of its course.
   *
   * Removing the group's last placement records the group as dismissed, or
   * `placeMissing` would read the gap as an accident and refill it on the
   * next load. Adding any sitting of the group back clears the record.
   */
  removePlacement(groupId, sessionId) {
    const matches = p => p.groupId === groupId
      && (sessionId === undefined || p.selectedSessionId === sessionId);
    if (!this.placements.some(matches)) return false;
    this._snapshot();
    this.placements = this.placements.filter(p => !matches(p));
    if (!this.placements.some(p => p.groupId === groupId)
        && !this.dismissedGroups.includes(groupId)) {
      this.dismissedGroups = [...this.dismissedGroups, groupId];
    }
    this._notify();
    return true;
  }

  /**
   * The student's correction to what counts as one class. Spec section 4.
   *
   * Placements of the affected type are dropped and re-made, because their
   * group ids no longer exist once the grouping changes.
   */
  setOptionGroupOverride(courseKey, type, mode) {
    this._snapshot();
    const key = `${courseKey}|${type}`;
    if (mode) {
      this.overrides = { ...this.overrides, [key]: mode };
    } else {
      this.overrides = { ...this.overrides };
      delete this.overrides[key];
    }
    // Regrouping renames the type's group ids, so dismissals recorded under
    // the old ones would never match anything again. Dropping them means the
    // regrouped type starts fully placed, which is also the least surprising
    // answer to changing what counts as one class.
    this.dismissedGroups = this.dismissedGroups.filter(
      id => !id.startsWith(`${courseKey}|${type}|`)
    );
    this._invalidate();

    const stale = new Set(
      this.placements
        .filter(p => p.courseKey === courseKey)
        .map(p => p.groupId)
    );
    const kept = this.placements.filter(p => !stale.has(p.groupId));
    const regrouped = this.optionGroups.filter(
      g => g.courseKey === courseKey && !kept.some(p => p.groupId === g.groupId)
    );
    this.placements = placeGroups(kept, regrouped, this.groupIndex).placements;
    this._notify();
  }

  /**
   * Re-place everything from scratch. Spec 8.3, the old autoPlaceAll.
   *
   * Only ever called deliberately, because it is allowed to move classes the
   * student arranged by hand. Pinned placements survive it.
   */
  reoptimise() {
    this._snapshot();
    const pinned = this.placements.filter(p => p.pinned);

    // Which sessions of each group the pinned placements already occupy. A
    // group with a pinned extra sitting can still have its unpinned first
    // placement re-chosen, but not onto a session the student already
    // attends, or the two would collapse into one block.
    const pinnedSessions = new Map();
    for (const p of pinned) {
      if (!pinnedSessions.has(p.groupId)) pinnedSessions.set(p.groupId, new Set());
      pinnedSessions.get(p.groupId).add(p.selectedSessionId);
    }
    const unpinnedGroups = new Set(
      this.placements.filter(p => !p.pinned).map(p => p.groupId)
    );
    const dismissed = new Set(this.dismissedGroups);

    const loose = this.activeCourses.map(course => ({
      courseKey: course.courseKey,
      groups: deriveOptionGroups(course, this.overrides)
        // A dismissed group was emptied on purpose; re-optimising rearranges
        // what is there, it does not resurrect what was removed.
        .filter(g => !dismissed.has(g.groupId))
        // Loose means holding an unpinned placement, or none at all.
        .filter(g => unpinnedGroups.has(g.groupId) || !pinnedSessions.has(g.groupId))
        .map(g => pinnedSessions.has(g.groupId)
          ? {
              ...g,
              sessions: g.sessions.filter(
                s => !pinnedSessions.get(g.groupId).has(s.sessionId)
              ),
            }
          : g)
        .filter(g => g.sessions.length > 0),
    }));
    this.placements = placeCourses(pinned, loose, this.groupIndex).placements;
    this._notify();
  }

  /** Course codes that came from the warehouse and could be refreshed. */
  get warehouseCourseKeys() {
    return this.activeCourses
      .filter(c => c.origin === 'warehouse')
      .map(c => c.courseKey);
  }

  /**
   * Take a newer publication's data for the courses already added.
   *
   * A class can move between publications, which means a saved placement can
   * point at a session that no longer exists. Those are dropped and the gap
   * refilled; everything still resolvable is left exactly where it was,
   * including anything pinned.
   *
   * A course the new publication does not carry is kept and marked stale
   * rather than deleted. It is more likely that a code was withdrawn from the
   * index than that the student stopped taking it, and silently emptying part
   * of their timetable would be the worse mistake.
   */
  refreshFromWarehouse(fetched, notFound, publicationId, publishedAt) {
    this._snapshot();

    for (const course of fetched || []) {
      const at = this.sourceData.courses.findIndex(
        c => c.courseKey === course.courseKey
      );
      if (at >= 0) {
        this.sourceData.courses[at] = { ...course, stale: false };
      } else {
        this.sourceData.courses.push(course);
      }
    }

    const missing = new Set(notFound || []);
    for (const course of this.sourceData.courses) {
      if (missing.has(course.courseKey)) course.stale = true;
    }

    this.publicationId = publicationId || this.publicationId;
    // Refreshing onto a newer publication moves the date with it, so a
    // reprint does not still claim the freshness of the old one.
    this.publishedAt = publishedAt || this.publishedAt;
    this._invalidate();

    // Resolve each placement rather than only checking that its group
    // survived. A moved class leaves the group standing and takes the session
    // with it, so a group-only check keeps a placement that renders nothing,
    // still occupies its group, and therefore stops the refill below from
    // filling the gap. On the 28 August 2026 republish that emptied ten of a
    // student's twelve blocks while the toast said nothing had changed, and
    // it only came back because opening the page again prunes.
    const index = this.groupIndex;
    const kept = this.placements.filter(p => eventForPlacement(p, index) !== null);
    const dropped = this.placements.length - kept.length;
    this.placements = kept;

    const placedGroups = new Set(this.placements.map(p => p.groupId));
    const dismissed = new Set(this.dismissedGroups);
    const gaps = this.activeCourses
      .map(course => ({
        courseKey: course.courseKey,
        groups: deriveOptionGroups(course, this.overrides)
          .filter(g => !placedGroups.has(g.groupId) && !dismissed.has(g.groupId)),
      }))
      .filter(c => c.groups.length > 0);
    if (gaps.length) {
      this.placements = placeCourses(this.placements, gaps, this.groupIndex).placements;
    }

    this._notify();
    return { moved: dropped, stale: [...missing] };
  }

  /**
   * Drop placements that no longer resolve to a class.
   *
   * Two ways that happens, and both leave the same symptom: a placement that
   * occupies its group, renders nothing, and stops `placeMissing` refilling
   * the gap, so the class silently vanishes from the timetable.
   *
   * The group can go, because group ids are derived from the grouping rules
   * and changing those rules strands everything saved under the old ones. Or
   * the group can survive while the session inside it goes, which is what a
   * republished timetable does when it moves one class and leaves the rest.
   *
   * Resolving the placement outright covers both, rather than checking for
   * the first and being surprised by the second.
   */
  pruneDanglingPlacements() {
    const index = this.groupIndex;
    const kept = this.placements.filter(p => eventForPlacement(p, index) !== null);
    const dropped = this.placements.length - kept.length;
    if (dropped) {
      this.placements = kept;
      this._invalidate();
    }
    return dropped;
  }

  /**
   * Place anything on the timetable that has no placement yet.
   *
   * Skips groups the student emptied themselves: a gap they made is a
   * decision, not something to be repaired on the next load.
   */
  placeMissing() {
    const placedGroups = new Set(this.placements.map(p => p.groupId));
    const dismissed = new Set(this.dismissedGroups);
    const missing = this.activeCourses
      .map(course => ({
        courseKey: course.courseKey,
        groups: deriveOptionGroups(course, this.overrides).filter(
          g => !placedGroups.has(g.groupId) && !dismissed.has(g.groupId)
        ),
      }))
      .filter(c => c.groups.length > 0);
    if (missing.length === 0) return false;

    this._snapshot();
    this.placements = placeCourses(
      this.placements,
      missing,
      this.groupIndex
    ).placements;
    this._notify();
    return true;
  }

  // History

  _snapshot() {
    this.history.push(this._current());
    this.future = [];
    if (this.history.length > MAX_HISTORY) this.history.shift();
  }

  _restore(snapshot) {
    this.courseKeys = [...snapshot.courseKeys];
    this.placements = JSON.parse(JSON.stringify(snapshot.placements));
    this.overrides = { ...snapshot.overrides };
    // Older saved histories predate dismissals, so the field can be absent.
    this.dismissedGroups = [...(snapshot.dismissedGroups || [])];
    this._invalidate();
  }

  _current() {
    return {
      courseKeys: [...this.courseKeys],
      placements: JSON.parse(JSON.stringify(this.placements)),
      overrides: { ...this.overrides },
      dismissedGroups: [...this.dismissedGroups],
    };
  }

  undo() {
    if (this.history.length === 0) return false;
    this.future.push(this._current());
    this._restore(this.history.pop());
    this._notify();
    return true;
  }

  redo() {
    if (this.future.length === 0) return false;
    this.history.push(this._current());
    this._restore(this.future.pop());
    this._notify();
    return true;
  }

  canUndo() {
    return this.history.length > 0;
  }

  canRedo() {
    return this.future.length > 0;
  }

  onChange(callback) {
    this._listeners.push(callback);
    return () => {
      this._listeners = this._listeners.filter(cb => cb !== callback);
    };
  }

  _notify() {
    this._invalidate();
    for (const cb of this._listeners) {
      try { cb(); } catch (e) { console.error('TimetableState listener error:', e); }
    }
  }

  /** The saved shape, spec section 12. */
  toSaved() {
    return {
      version: 3,
      publicationId: this.publicationId,
      publishedAt: this.publishedAt,
      courses: this.sourceData.courses,
      courseKeys: this.courseKeys,
      optionGroupOverrides: this.overrides,
      placements: this.placements,
      dismissedGroups: this.dismissedGroups,
      history: this.history.slice(-MAX_HISTORY),
      future: this.future.slice(-MAX_HISTORY),
      savedAt: new Date().toISOString(),
    };
  }
}

// Persistence and migration

/**
 * v1 held the extract response plus a flat list of calendar events. It was
 * written by the upload page and is still read, because a student who has not
 * opened the calendar since should not lose their timetable.
 */
function migrateV1toV2(v1Data) {
  if (!v1Data) return null;
  const sourceData = TimetableState.fromExtractResponse(v1Data);
  if (!sourceData.courses.length) return null;

  const placements = [];
  for (const event of (v1Data.calendar_events || [])) {
    const title = event.course || '';
    const courseKey = courseCodeFromTitle(title) || titleDerivedKey(title);
    const course = sourceData.courses.find(c => c.courseKey === courseKey);
    if (!course) continue;

    const match = course.sessions.find(s =>
      s.type === normalizeType(event.type || 'Other') &&
      s.day === event.day &&
      timeToMins(s.startTime) === timeToMins(event.start_time || '') &&
      timeToMins(s.endTime) === timeToMins(event.end_time || '')
    );
    if (match && !placements.some(p => p.streamId === match.streamId)) {
      placements.push({ courseKey, streamId: match.streamId });
    }
  }
  return { version: 2, sourceData, placements };
}

/**
 * v2 keyed one placement per (course, type). v3 keys one per option group.
 *
 * Migrated placements are left unpinned. v2 recorded no difference between a
 * class the student dragged into place and one auto-placement chose, so
 * pinning them all would quietly make "re-optimise" do nothing, and pinning
 * none of them only means re-optimise is free to improve on a choice that was
 * probably not theirs anyway. Either way nothing moves on load: the exact
 * session each placement resolved to is preserved.
 */
function migrateV2toV3(v2Data) {
  if (!v2Data) return null;

  // A v2 payload from storage nests the placements; one straight out of
  // migrateV1toV2 has already flattened them.
  const sourceData = v2Data.sourceData;
  if (!sourceData || !(sourceData.courses || []).length) return null;
  const oldPlacements = v2Data.placements
    || (v2Data.scheduleState && v2Data.scheduleState.placements)
    || [];

  // v2 courses carry `streams` and a title-derived `courseId`; v3 wants
  // `sessions` and a course code where the title offers one. A payload
  // straight out of migrateV1toV2 already has v3 courses with a `courseKey`
  // and no `courseId`, and that key is kept: rebuilding it from the code alone
  // left an upload whose title has none keyed `undefined`, and JSON then lost
  // the key on save, so the course fell off the timetable on the next load.
  const remap = new Map();
  const courses = sourceData.courses.map(course => {
    const code = course.code !== undefined ? course.code : courseCodeFromTitle(course.title);
    const courseKey = course.courseKey || code || course.courseId
      || titleDerivedKey(course.title);
    remap.set(course.courseId, courseKey);
    return {
      courseKey,
      origin: 'upload',
      code,
      title: course.title,
      faculty: null,
      department: null,
      sourceFile: course.sourceFile || null,
      sessions: (course.streams || course.sessions || []).map(stream => _session({
        type: stream.type,
        day: stream.day,
        startTime: stream.startTime,
        endTime: stream.endTime,
        room: stream.room,
        staff: Array.isArray(stream.staff)
          ? stream.staff
          : (stream.staff ? [stream.staff] : []),
        streamLabel: stream.groupLabel || stream.streamLabel,
        weeksRaw: typeof stream.weeks === 'string' ? stream.weeks : stream.weeksRaw,
        weeks: Array.isArray(stream.weeks) ? stream.weeks : null,
      })),
    };
  });

  const placements = [];
  for (const course of courses) {
    const groups = deriveOptionGroups(course, {});
    const wanted = oldPlacements
      .filter(p => (remap.get(p.courseId) || p.courseKey) === course.courseKey)
      .map(p => p.selectedStreamId || p.streamId)
      .filter(Boolean);

    for (const streamId of wanted) {
      const group = groups.find(g => g.sessions.some(s => s.streamId === streamId));
      if (!group || placements.some(p => p.groupId === group.groupId)) continue;
      const session = group.sessions.find(s => s.streamId === streamId);
      placements.push({
        courseKey: course.courseKey,
        groupId: group.groupId,
        selectedSessionId: session.sessionId,
        pinned: false,
      });
    }
  }

  return {
    version: 3,
    publicationId: null,
    courses,
    courseKeys: courses.map(c => c.courseKey),
    optionGroupOverrides: {},
    placements,
    history: [],
    future: [],
  };
}

/**
 * The most recent saved timetable, upgraded to v3.
 *
 * Storage is passed in so this can be exercised without a browser. The older
 * readers stay because a student with no network and a saved timetable has to
 * keep working, which is the one thing this feature must not break.
 */
function readSavedState(storage) {
  const store = storage || (typeof localStorage !== 'undefined' ? localStorage : null);
  if (!store) return null;

  const parse = key => {
    const raw = store.getItem(key);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch (e) {
      console.warn(`Ignoring unreadable ${key}:`, e.message);
      return null;
    }
  };

  const v3 = parse(STORAGE_KEY_V3);
  if (v3 && v3.version === 3) return repairLostCourseKeys(v3);

  const v2 = parse(STORAGE_KEY_V2);
  if (v2 && v2.version === 2) return migrateV2toV3(v2);

  const v1 = parse(STORAGE_KEY_V1);
  if (v1) return migrateV2toV3(migrateV1toV2(v1));

  return null;
}

//: The group-id and override prefix of a course whose key was lost.
const LOST_KEY_PREFIX = 'undefined|';

/**
 * Give back the keys a v1 migration lost, in a timetable saved while it did.
 *
 * migrateV2toV3 used to key an upload with no recognisable code `undefined`.
 * JSON then dropped the key from the course and wrote `null` into
 * courseKeys, so on the next load the course matched nothing and vanished,
 * while its placements, dismissals and overrides stayed filed under
 * "undefined|". Each keyless course gets the key the extract reader would
 * have given it. With one such course everything under "undefined|" is its
 * own and is renamed, keeping any class the student placed by hand. With
 * several, they had already collided under that prefix and which course owned
 * what is gone, so those entries are dropped and auto-placement refills them.
 * A course is put back on the timetable only where a `null` in courseKeys says
 * it was on it: removing it had filtered the undefined out entirely.
 *
 * Undo history is cleared when anything is repaired, since every snapshot in
 * it still names the old groups.
 */
function repairLostCourseKeys(saved) {
  const courses = saved.courses || [];
  if (courses.every(c => c.courseKey)) return saved;

  const repaired = [];
  const fixedCourses = courses.map(c => {
    if (c.courseKey) return c;
    const courseKey = c.code || courseCodeFromTitle(c.title) || titleDerivedKey(c.title);
    repaired.push(courseKey);
    return { ...c, courseKey };
  });

  const wasOnTimetable = (saved.courseKeys || []).includes(null);
  const courseKeys = (saved.courseKeys || [])
    .filter(k => typeof k === 'string')
    .concat(wasOnTimetable ? repaired : []);

  const only = repaired.length === 1 ? repaired[0] : null;
  const rename = id => only + '|' + id.slice(LOST_KEY_PREFIX.length);
  const lost = id => String(id).startsWith(LOST_KEY_PREFIX);

  const placements = (saved.placements || []).flatMap(p => {
    if (!lost(p.groupId)) return [p];
    return only ? [{ ...p, courseKey: only, groupId: rename(p.groupId) }] : [];
  });
  const dismissedGroups = (saved.dismissedGroups || []).flatMap(id => {
    if (!lost(id)) return [id];
    return only ? [rename(id)] : [];
  });
  const optionGroupOverrides = {};
  for (const [key, mode] of Object.entries(saved.optionGroupOverrides || {})) {
    if (!lost(key)) optionGroupOverrides[key] = mode;
    else if (only) optionGroupOverrides[rename(key)] = mode;
  }

  return {
    ...saved,
    courses: fixedCourses,
    courseKeys,
    placements,
    dismissedGroups,
    optionGroupOverrides,
    history: [],
    future: [],
  };
}

/**
 * Save, and say whether it worked.
 *
 * A full or disabled localStorage used to be swallowed into a console warning,
 * which meant a student could arrange a whole timetable and lose it without
 * ever being told (E14).
 */
function writeSavedState(saved, storage) {
  const store = storage || (typeof localStorage !== 'undefined' ? localStorage : null);
  if (!store) return { ok: false, error: 'This browser is not storing anything.' };
  try {
    store.setItem(STORAGE_KEY_V3, JSON.stringify(saved));
    return { ok: true };
  } catch (e) {
    return {
      ok: false,
      error: e && e.name === 'QuotaExceededError'
        ? 'There is no room left in this browser to save your timetable.'
        : 'This browser would not save your timetable.',
    };
  }
}
