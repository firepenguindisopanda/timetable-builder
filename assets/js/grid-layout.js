'use strict';

/**
 * Where blocks sit side by side instead of on top of each other.
 *
 * Two classes at the same hour used to render as two full-width blocks, one
 * exactly covering the other. The one behind could not be seen, clicked or
 * dragged, which made the commonest conflict impossible to fix by hand: the
 * class a student wanted to move was the one they could not reach.
 *
 * The layout is decided by visual overlap alone, not by whether two classes
 * genuinely collide. A lecture and its week-10 relocation never clash, but
 * they still sit on the same hour of the same day, and each still needs to be
 * reachable.
 */

/**
 * Assign each event of one day a column within its overlap run.
 *
 * Returns one record per event, in the order given: `{ event, col, cols }`,
 * where `col` is the event's column and `cols` how many columns its run
 * needs. An event overlapping nothing gets `{ col: 0, cols: 1 }` and renders
 * full width.
 *
 * Events are walked in start order and dropped into the first column whose
 * last occupant has ended. A run closes when every open column has ended, at
 * which point everything in it shares the widest column count the run
 * reached, so blocks in one pile-up line up instead of overhanging each
 * other.
 */
function layoutDayEvents(events) {
  const order = [...events].sort((a, b) => {
    const startDiff = timeToMins(a.startTime) - timeToMins(b.startTime);
    if (startDiff !== 0) return startDiff;
    // Longer first, so the block spanning the run claims the leftmost lane.
    const endDiff = timeToMins(b.endTime) - timeToMins(a.endTime);
    if (endDiff !== 0) return endDiff;
    return String(a.groupId || '').localeCompare(String(b.groupId || ''));
  });

  const records = new Map();
  //: End minute of the latest occupant of each open column.
  let columnEnds = [];
  //: Records of the run being built, closed when every column has ended.
  let run = [];

  const closeRun = () => {
    const cols = columnEnds.length;
    for (const record of run) record.cols = cols;
    columnEnds = [];
    run = [];
  };

  for (const event of order) {
    const start = timeToMins(event.startTime);
    const end = Math.max(timeToMins(event.endTime), start + 1);

    if (columnEnds.length && columnEnds.every(colEnd => colEnd <= start)) {
      closeRun();
    }

    let col = columnEnds.findIndex(colEnd => colEnd <= start);
    if (col === -1) {
      col = columnEnds.length;
      columnEnds.push(end);
    } else {
      columnEnds[col] = end;
    }

    const record = { event, col, cols: 1 };
    records.set(event, record);
    run.push(record);
  }
  closeRun();

  return events.map(event => records.get(event));
}
