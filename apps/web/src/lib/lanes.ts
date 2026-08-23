/** Assign overlapping spans to side-by-side lanes (Google-Calendar style):
 * transitively-overlapping items form a cluster; each gets the first free lane,
 * and every item in the cluster is widened to 1/lanes so they sit beside each
 * other in a fixed-width column. Shared by the calendar week view and the
 * schedule grid so both resolve conflicts the same way.
 *
 * `opts.laneKey` tags each item's lane; `opts.reuse` items (a schedule-tagged
 * event) join the lane of a same-key item (its schedule's block) even while it
 * overlaps — so an internship event renders INSIDE the internship column. */
export function packLanes<T extends { start: number; end: number }>(
  items: T[],
  opts?: { laneKey?: (it: T) => string | null; reuse?: (it: T) => boolean },
): { item: T; lane: number; lanes: number }[] {
  const laid = items
    .map((item) => ({ item, lane: 0, lanes: 1 }))
    // Containers (longer spans) first at a tie so a reusing event finds them.
    .sort((a, b) => a.item.start - b.item.start || b.item.end - a.item.end);
  let cluster: (typeof laid)[number][] = [];
  let clusterEnd = -Infinity;
  let colEnds: number[] = [];
  let colKeys: (string | null)[] = [];
  const flush = () => {
    const lanes = colEnds.length || 1;
    for (const c of cluster) c.lanes = lanes;
    cluster = [];
    colEnds = [];
    colKeys = [];
  };
  for (const s of laid) {
    if (s.item.start >= clusterEnd) flush(); // no overlap with cluster → new one
    const key = opts?.laneKey?.(s.item) ?? null;
    let lane = -1;
    if (key != null && opts?.reuse?.(s.item))
      lane = colKeys.findIndex((k) => k === key); // ride a same-schedule lane
    if (lane === -1) lane = colEnds.findIndex((e) => e <= s.item.start);
    if (lane === -1) {
      lane = colEnds.length;
      colEnds.push(s.item.end);
      colKeys.push(key);
    } else {
      colEnds[lane] = Math.max(colEnds[lane], s.item.end);
      if (key != null) colKeys[lane] = key;
    }
    s.lane = lane;
    cluster.push(s);
    clusterEnd = Math.max(clusterEnd, s.item.end);
  }
  flush();
  return laid;
}
