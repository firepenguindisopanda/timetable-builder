'use strict';

/**
 * Matching a typed query against the course index.
 *
 * Shared by the explorer's course list and the calendar's course picker, so a
 * search that finds a course on one page finds it on the other. Deliberately
 * free of markup: the two pages have different stylesheets and render the same
 * facts differently.
 *
 * The index is the payload from `/explore/courses.json`, about 1,100 rows and
 * 44 KB gzipped, fetched once. Everything here runs against that in memory, so
 * typing costs no requests.
 */

const SEARCH_TOTAL_WEEKS = 12;

/**
 * One lowercased string per course, holding everything worth matching on.
 *
 * Cached on the course object because it is rebuilt on every keystroke
 * otherwise, across a thousand courses.
 *
 * The code appears twice, with and without its space, so that "comp1601" and
 * "comp 1601" both hit. That is how students actually type a course code, and
 * it is the same accommodation `resolve_published_code` makes on the server.
 */
function courseHaystack(course) {
  if (course._hay === undefined) {
    course._hay = [
      course.code,
      String(course.code || '').replace(/\s+/g, ''),
      course.title,
      course.department,
      course.faculty,
      (course.rooms || []).join(' '),
      (course.staff || []).join(' '),
    ].join(' ').toLowerCase();
  }
  return course._hay;
}

/**
 * Whether a course matches every word of a query.
 *
 * Words are ANDed rather than ORed, so "comp lab" narrows instead of widening.
 */
function courseMatchesQuery(course, query) {
  const terms = String(query || '').toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return true;
  const hay = courseHaystack(course);
  return terms.every(term => hay.indexOf(term) !== -1);
}

/**
 * Courses matching a query, most useful first.
 *
 * A code match outranks a title match, which outranks a match buried in a room
 * or a lecturer name, because a student typing "COMP 1601" wants that course
 * and not the twelve others taught in the same room.
 */
function searchCourses(courses, query, limit) {
  const cleaned = String(query || '').trim().toLowerCase();
  const matches = (courses || []).filter(c => courseMatchesQuery(c, cleaned));

  if (cleaned) {
    const rank = course => {
      const code = String(course.code || '').toLowerCase();
      if (code === cleaned || code.replace(/\s+/g, '') === cleaned.replace(/\s+/g, '')) return 0;
      if (code.indexOf(cleaned) === 0) return 1;
      if (String(course.title || '').toLowerCase().indexOf(cleaned) !== -1) return 2;
      return 3;
    };
    matches.sort((a, b) => rank(a) - rank(b) || String(a.code).localeCompare(String(b.code)));
  }

  return limit ? matches.slice(0, limit) : matches;
}

/** Case and spacing removed, which is how two spellings of a code are compared. */
function courseCodeKey(text) {
  return String(text || '').replace(/\s+/g, '').toUpperCase();
}

/**
 * Index every published code by its match key.
 *
 * Cached on the array itself, because a paste of forty codes would otherwise
 * rebuild it forty times over a thousand courses.
 */
function courseCodeIndex(courses) {
  if (!courses._codeIndex) {
    const index = new Map();
    let maxTokens = 1;
    for (const course of courses) {
      if (!index.has(courseCodeKey(course.code))) {
        index.set(courseCodeKey(course.code), course.code);
      }
      maxTokens = Math.max(maxTokens, String(course.code || '').split(/\s+/).length);
    }
    // How far the parser looks ahead when a line has no separators. Taken
    // from the data rather than picked: most codes are two words, but the
    // publication also carries "AGRI 6620 STATISTICS", "PSYC 6102 / 7002" and
    // "FOUN 1001 (FULL & PART-TIME)", which is five.
    Object.defineProperty(courses, '_codeIndex', {
      value: { index, maxTokens },
      enumerable: false,
    });
  }
  return courses._codeIndex;
}

/**
 * Read a pasted list of course codes.
 *
 * This is how a student actually has their courses: off a registration
 * screenshot or a WhatsApp message, so the separators are whatever they were
 * that day. Commas, semicolons and newlines are unambiguous and split first.
 *
 * Whitespace cannot simply split too, because "CAPE BIOL" and
 * "FOUN 1001 (FULL & PART-TIME)" are single published codes with spaces in
 * them. So within a fragment the tokens are walked greedily, longest match
 * first, against the published index. That resolves "COMP1601 COMP1602" into
 * two courses and "CAPE BIOL" into one, without either rule being guessed at.
 *
 * Anything that matches nothing is returned rather than dropped: a student
 * needs to see that their sixth course was not understood.
 */
function parseCourseCodeList(text, courses) {
  const { index, maxTokens } = courseCodeIndex(courses || []);
  const found = [];
  const unknown = [];
  const seen = new Set();

  const accept = code => {
    if (seen.has(code)) return;
    seen.add(code);
    found.push(code);
  };

  for (const fragment of String(text || '').split(/[\n,;]+/)) {
    const trimmed = fragment.trim();
    if (!trimmed) continue;

    const whole = index.get(courseCodeKey(trimmed));
    if (whole) {
      accept(whole);
      continue;
    }

    const tokens = trimmed.split(/\s+/);
    // Consecutive words that matched nothing are reported as the run they came
    // from rather than one at a time, so a stray sentence in a pasted list
    // reads as "my sem 1 courses:" and not as four separate complaints.
    let stray = [];
    const flushStray = () => {
      if (stray.length) unknown.push(stray.join(' '));
      stray = [];
    };

    let i = 0;
    while (i < tokens.length) {
      let matched = 0;
      // Longest first, so "CAPE BIOL" wins over a bare "CAPE".
      for (let take = Math.min(maxTokens, tokens.length - i); take >= 1; take--) {
        const hit = index.get(courseCodeKey(tokens.slice(i, i + take).join(' ')));
        if (hit) {
          accept(hit);
          matched = take;
          break;
        }
      }
      if (matched) {
        flushStray();
        i += matched;
      } else {
        stray.push(tokens[i]);
        i += 1;
      }
    }
    flushStray();
  }

  return { codes: found, unknown };
}

/** The week numbers packed into a bitmask, where bit 0 is week 1. */
function weeksFromMask(mask) {
  const weeks = [];
  for (let w = 1; w <= SEARCH_TOTAL_WEEKS; w++) {
    if ((mask >> (w - 1)) & 1) weeks.push(w);
  }
  return weeks;
}

/** What the week meter says to a screen reader. */
function weekMaskLabel(mask) {
  const weeks = weeksFromMask(mask);
  if (!weeks.length) return 'No teaching weeks recorded';
  return 'Runs in week' + (weeks.length > 1 ? 's ' : ' ') + weeks.join(', ');
}
