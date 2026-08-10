'use strict';

/**
 * Deciding what counts as one class.
 *
 * A course's sessions arrive as a flat list. Some of them are alternatives a
 * student picks between (lab section L1 or L2), and some are separate classes
 * they all attend (the Monday lecture and the Wednesday one). Nothing in the
 * published data says which, so this file guesses, and the guess decides what
 * lands on the calendar.
 *
 * An option group is a set of mutually exclusive alternatives. One placement
 * per option group, one selected session per placement. Two sessions in
 * different groups are both attended; two in the same group are a choice.
 */

/**
 * Above this many hours a week, one activity type for one course stops being a
 * schedule and starts being a menu.
 *
 * Not a guess. Of the 1,665 (course, type) groups in the warehouse, 978 hold a
 * single session, and those are the only ones whose reading is unambiguous.
 * They say what one activity type costs a student in a week: median 2 hours,
 * 3 at the 90th percentile, 5 at the 99th. This is twice the 90th.
 *
 * Getting it wrong in one direction shows a student an extra class they can
 * delete. Getting it wrong in the other buries them: FOUN 1101 publishes 33
 * unlabelled tutorial sessions, and reading those as obligations puts 33 hours
 * of tutorial on a 40-hour grid for one course.
 */
const MENU_CEILING_HOURS = 6.0;

/**
 * Stands in for an activity type the publication left empty, so that grouping
 * has a key to work with. Five sessions campus-wide arrive this way. It is not
 * folded into "Other", which is a real published type that other courses use.
 */
const UNSPECIFIED_TYPE = 'Unspecified';

function _typeOf(session) {
  return session.type || UNSPECIFIED_TYPE;
}

function _minutes(session) {
  return timeToMins(session.endTime) - timeToMins(session.startTime);
}

function _hours(sessions) {
  return sessions.reduce((total, s) => total + _minutes(s), 0) / 60;
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
 * Three rules, and the order matters:
 *
 * 1. Over the ceiling, everything of this type is one menu. This is the rule
 *    that does the heavy lifting. It is also what makes rule 2 safe: left
 *    alone, rule 2 turns COMP 1601's ten lab sections into eight obligations,
 *    because only one of the ten carries a label. At 20 hours the ceiling has
 *    already claimed that group before rule 2 sees it, and the same is true of
 *    every other badly labelled group large enough to matter.
 * 2. Labelled sessions are alternatives to each other. 47 groups under the
 *    ceiling are fully labelled, and clustering those by time would place all
 *    five of a course's tutorial sections.
 * 3. Whatever is left clusters by time overlap, and anything that does not
 *    overlap is a class in its own right. This keeps the Monday-and-Wednesday
 *    lecture pair, 297 of which the warehouse holds, reading as two lectures.
 *
 * COMP 1601's lectures are the case that pins rules 2 and 3 apart. One of the
 * five carries "G2", so rule 2 takes that one, and rule 3 clusters the rest
 * into the Monday lecture, the two Tuesday rooms, and the Wednesday lecture.
 * Four placements and a room choice, which is the reading the spec argued for.
 */
function _groupsForType(courseKey, type, sessions, override) {
  const ordered = sessionsInTimetableOrder(sessions);

  if (override === 'menu') {
    return [_group(courseKey, type, 'override', ordered, 'all')];
  }
  if (override !== 'split' && _hours(ordered) > MENU_CEILING_HOURS) {
    return [_group(courseKey, type, 'ceiling', ordered, 'all')];
  }

  // "split" is the student saying these are not alternatives, so labels are
  // set aside along with the ceiling and everything clusters on time alone.
  const useLabels = override !== 'split' && ordered.some((s) => s.streamLabel);
  const groups = [];
  if (useLabels) {
    groups.push(
      _group(
        courseKey,
        type,
        'labelled',
        ordered.filter((s) => s.streamLabel),
        'labelled'
      )
    );
  }

  const remaining = useLabels ? ordered.filter((s) => !s.streamLabel) : ordered;
  for (const cluster of _overlapClusters(remaining)) {
    groups.push(
      _group(
        courseKey,
        type,
        cluster.length > 1 ? 'overlap' : 'single',
        cluster,
        // The earliest session identifies the cluster: two clusters cannot
        // start at the same day and time, or they would overlap and be one.
        `${cluster[0].day}-${cluster[0].startTime}`
      )
    );
  }
  return groups;
}

/**
 * Every option group for a course.
 *
 * `overrides` is the student's correction, keyed "courseKey|type", with the
 * value "menu" to say these are alternatives or "split" to say they are not.
 * No rule gets all 457 ambiguous groups right, so the override is part of the
 * design rather than an escape hatch.
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
