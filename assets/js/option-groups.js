'use strict';

/**
 * Deciding what counts as one class.
 *
 * A course's sessions arrive as a flat list: every sitting of every lecture,
 * lab and tutorial CELCAT publishes for it. A student attends one of each per
 * week, so what they need is a choice per activity type, not a copy of the
 * department's whole schedule.
 *
 * An option group is a set of mutually exclusive alternatives. One placement
 * per option group, one selected session per placement. Two sessions in
 * different groups are both attended; two in the same group are a choice.
 */

/**
 * Stands in for an activity type the publication left empty, so that grouping
 * has a key to work with. Five sessions campus-wide arrive this way. It is not
 * folded into "Other", which is a real published type that other courses use.
 */
const UNSPECIFIED_TYPE = 'Unspecified';

function _typeOf(session) {
  return session.type || UNSPECIFIED_TYPE;
}

/**
 * Sort into the order the group ids are built from.
 *
 * Shared with the placement rules, whose tie-break is "earliest day, then
 * earliest start", which is this order.
 *
 * Ids have to survive a reload, so nothing here may depend on the order the
 * server happened to return rows in. Room and session id are the tiebreakers
 * that make two sessions at the same time on the same day distinguishable.
 */
function sessionsInTimetableOrder(sessions) {
  return [...sessions].sort((a, b) => {
    const dayDiff = DAYS.indexOf(a.day) - DAYS.indexOf(b.day);
    if (dayDiff !== 0) return dayDiff;
    const startDiff = timeToMins(a.startTime) - timeToMins(b.startTime);
    if (startDiff !== 0) return startDiff;
    const endDiff = timeToMins(a.endTime) - timeToMins(b.endTime);
    if (endDiff !== 0) return endDiff;
    const roomDiff = String(a.room || '').localeCompare(String(b.room || ''));
    if (roomDiff !== 0) return roomDiff;
    return (a.sessionId || 0) - (b.sessionId || 0);
  });
}

function _overlaps(a, b) {
  return (
    a.day === b.day &&
    timesOverlap(a.startTime, a.endTime, b.startTime, b.endTime)
  );
}

/**
 * Split sessions into clusters that cannot be attended together.
 *
 * Sessions at the same day and time in different rooms land in one cluster,
 * which is the right reading of an overflow or video-linked room: a choice of
 * where to sit, not two classes.
 */
function _overlapClusters(sessions) {
  const clusters = [];
  for (const session of sessions) {
    const existing = clusters.find((c) => c.some((s) => _overlaps(s, session)));
    if (existing) {
      existing.push(session);
    } else {
      clusters.push([session]);
    }
  }
  return clusters;
}

function _group(courseKey, type, reason, sessions, discriminator) {
  return {
    groupId: `${courseKey}|${type}|${discriminator}`,
    courseKey,
    type,
    reason,
    sessions,
  };
}

/**
 * The option groups for one activity type of one course.
 *
 * A student attends one lecture, one lab and one tutorial per course per week.
 * Every session CELCAT publishes under an activity type is therefore a sitting
 * of the same class, and the whole set is one choice.
 *
 * This is worth stating plainly because the data does not say it and cannot be
 * made to. An earlier version of this file inferred the grouping from stream
 * labels and time overlaps, which read COMP 1601's five unlabelled lectures as
 * four separate obligations and put seventeen blocks on a five-course
 * timetable where a student expects ten. The rule is institutional, not
 * derivable, so it is written down rather than guessed at.
 *
 * A course that genuinely runs more than one of a type in a week is handled by
 * the student splitting the group, which is what the override is for.
 */
function _groupsForType(courseKey, type, sessions, override) {
  const ordered = sessionsInTimetableOrder(sessions);

  if (override !== 'split') {
    return [
      _group(
        courseKey,
        type,
        ordered.length > 1 ? 'sittings' : 'single',
        ordered,
        'all'
      ),
    ];
  }

  // Split: the student has said this course really does run several of these a
  // week. Sessions that overlap each other are still a choice, since nobody
  // can be in two rooms at once.
  return _overlapClusters(ordered).map((cluster) =>
    _group(
      courseKey,
      type,
      cluster.length > 1 ? 'overlap' : 'split',
      cluster,
      // The earliest session identifies the cluster: two clusters cannot start
      // at the same day and time, or they would overlap and be one.
      `${cluster[0].day}-${cluster[0].startTime}`
    )
  );
}

/**
 * Every option group for a course.
 *
 * `overrides` is the student's correction, keyed "courseKey|type". Only
 * "split" does anything now: it says this course runs more than one of these
 * a week rather than offering a choice of one.
 */
function deriveOptionGroups(course, overrides) {
  const byType = new Map();
  for (const session of course.sessions || []) {
    const type = _typeOf(session);
    if (!byType.has(type)) byType.set(type, []);
    byType.get(type).push(session);
  }

  const groups = [];
  for (const type of [...byType.keys()].sort()) {
    const key = `${course.courseKey}|${type}`;
    groups.push(
      ..._groupsForType(
        course.courseKey,
        type,
        byType.get(type),
        overrides && overrides[key]
      )
    );
  }
  return groups;
}

/** Whether a group is a choice between alternatives rather than a lone class. */
function isMenu(group) {
  return group.sessions.length > 1;
}
