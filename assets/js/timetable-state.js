'use strict';

function _formatTime(t) {
  if (!t) return "00:00";
  return minsToTime(timeToMins(t));
}

class TimetableState {
  constructor(sourceData, savedState) {
    this.sourceData = sourceData;
    this.placements = (savedState && savedState.placements) || [];
    this.history = (savedState && savedState.history) || [];
    this.future = (savedState && savedState.future) || [];
    this._listeners = [];
    this._maxHistory = 50;
  }

  static fromExtractResponse(data) {
    const courses = [];
    const seenCourseIds = new Set();

    if (!data) return { courses: [] };
    const entries = data.results || [];

    for (const result of entries) {
      const courseTitle = result.course_title || result.source_file || "Unknown";
      const courseId = courseTitle.toUpperCase().replace(/\s+/g, '-').replace(/[^a-zA-Z0-9_-]/g, '');

      if (seenCourseIds.has(courseId)) continue;
      seenCourseIds.add(courseId);

      const streams = [];
      const seenStreamIds = new Set();

      for (const entry of (result.entries || [])) {
        const type = normalizeType(entry.type);
        const streamId = computeStreamId(type, entry.day, entry.start_time, entry.end_time, entry.group_label);

        if (seenStreamIds.has(streamId)) continue;
        seenStreamIds.add(streamId);

        const startTime = _formatTime(entry.start_time);
        const endTime = _formatTime(entry.end_time);

        streams.push({
          streamId,
          type,
          typeKey: computeTypeKey(type, entry.group_label),
          day: entry.day,
          startTime,
          endTime,
          room: entry.room || null,
          staff: entry.staff || null,
          groupLabel: entry.group_label || null,
          weeks: entry.weeks || null,
          weekCount: entry.week_count || null,
        });
      }

      courses.push({
        courseId,
        title: courseTitle,
        sourceFile: result.source_file || null,
        streams,
      });
    }

    return { courses };
  }

  getPlacedEvents() {
    const events = [];
    for (const p of this.placements) {
      const course = this._findCourse(p.courseId);
      if (!course) continue;
      const stream = course.streams.find(s => s.streamId === p.selectedStreamId);
      if (!stream) continue;
      events.push({
        courseId: course.courseId,
        courseTitle: course.title,
        streamType: p.streamType,
        day: stream.day,
        startTime: stream.startTime,
        endTime: stream.endTime,
        room: stream.room,
        staff: stream.staff,
      });
    }
    return events;
  }

  getAvailableStreams(courseId, streamType) {
    const course = this._findCourse(courseId);
    if (!course) return [];
    // Filter by bare type (not typeKey) so that grouped streams (e.g., Lab-L1) are also matched
    return course.streams.filter(s => s.type === streamType);
  }

  getConflicts() {
    return findConflicts(this.getPlacedEvents());
  }

  _findCourse(courseId) {
    return this.sourceData.courses.find(c => c.courseId === courseId);
  }

  autoPlaceAll() {
    this._snapshot();
    this.placements = [];

    const typeOrder = ["Lecture", "Lab", "Tutorial", "Seminar", "Workshop", "Other"];

    for (const course of this.sourceData.courses) {
      for (const streamType of typeOrder) {
        const streams = this.getAvailableStreams(course.courseId, streamType);
        if (streams.length === 0) continue;

        let bestStream = streams[0];
        let bestScore = Infinity;

        for (const stream of streams) {
          let score = 0;
          for (const placed of this.placements) {
            const placedCourse = this._findCourse(placed.courseId);
            if (!placedCourse) continue;
            const placedStream = placedCourse.streams.find(s => s.streamId === placed.selectedStreamId);
            if (!placedStream) continue;
            if (placedStream.day === stream.day && timesOverlap(placedStream.startTime, placedStream.endTime, stream.startTime, stream.endTime)) {
              score++;
            }
          }
          if (score < bestScore) {
            bestScore = score;
            bestStream = stream;
          }
        }

        this.placements.push({
          courseId: course.courseId,
          streamType: streamType,
          selectedStreamId: bestStream.streamId,
        });
      }
    }

    this._notify();
  }

  moveEvent(courseId, streamType, newStreamId) {
    this._snapshot();
    const idx = this.placements.findIndex(p => p.courseId === courseId && p.streamType === streamType);
    if (idx >= 0) {
      this.placements[idx].selectedStreamId = newStreamId;
    } else {
      this.placements.push({ courseId, streamType, selectedStreamId: newStreamId });
    }
    this._notify();
  }

  removePlacement(courseId, streamType) {
    const idx = this.placements.findIndex(p => p.courseId === courseId && p.streamType === streamType);
    if (idx === -1) return;
    this._snapshot();
    this.placements.splice(idx, 1);
    this._notify();
  }

  _snapshot() {
    this.history.push(JSON.parse(JSON.stringify(this.placements)));
    this.future = [];
    if (this.history.length > this._maxHistory) this.history.shift();
  }

  undo() {
    if (this.history.length === 0) return false;
    this.future.push(JSON.parse(JSON.stringify(this.placements)));
    this.placements = this.history.pop();
    this._notify();
    return true;
  }

  redo() {
    if (this.future.length === 0) return false;
    this.history.push(JSON.parse(JSON.stringify(this.placements)));
    this.placements = this.future.pop();
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
    for (const cb of this._listeners) {
      try { cb(); } catch (e) { console.error("TimetableState listener error:", e); }
    }
  }
}
