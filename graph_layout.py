"""Deterministic node spacing and gently curved links with labels on the curve."""
from __future__ import annotations

import math
from collections import Counter


def positions_for(nodes: list[dict], links: list[dict]) -> tuple[dict, int]:
    count = len(nodes)
    height = 520 if count <= 6 else 640
    if not count:
        return {}, height
    if count <= 2:
        return {node["id"]: (500 + (i - (count-1)/2) * 340, 200) for i, node in enumerate(nodes)}, height
    points = {node["id"]: [500 + 360 * math.cos(-math.pi/2 + i*math.tau/count),
                            height/2 - 20 + (height/2-95)*math.sin(-math.pi/2 + i*math.tau/count)]
              for i, node in enumerate(nodes)}
    pairs = sorted({tuple(sorted((e["source"], e["target"]))) for e in links
                    if e["source"] in points and e["target"] in points and e["source"] != e["target"]})
    ids = list(points)
    degrees = Counter(uid for pair in pairs for uid in pair)
    hub = max(ids, key=lambda uid: degrees[uid])
    if count >= 7 and degrees[hub] >= count-2:
        # Keep a strong hub in the middle instead of producing a corner fan.
        slots = [(140,60),(380,60),(620,60),(860,60),(890,220),(890,380),
                 (740,535),(500,535),(260,535),(110,380),(110,220)]
        leaves = [uid for uid in ids if uid != hub]
        result = {hub: (500,300)}
        result.update({uid: slots[round(i*len(slots)/len(leaves)) % len(slots)] for i, uid in enumerate(leaves)})
        return result, height
    for step in range(180):
        force = {uid: [(500-p[0])*.002, (height/2-20-p[1])*.002] for uid, p in points.items()}
        for i, a in enumerate(ids):
            for b in ids[i+1:]:
                dx, dy = points[b][0]-points[a][0], points[b][1]-points[a][1]
                distance = max(1, math.hypot(dx, dy))
                push = max(0, 330-distance)*.035
                for axis, delta in enumerate((dx, dy)):
                    force[a][axis] -= delta/distance*push
                    force[b][axis] += delta/distance*push
        for a, b in pairs:
            dx, dy = points[b][0]-points[a][0], points[b][1]-points[a][1]
            distance = max(1, math.hypot(dx, dy))
            pull = (distance-250)*.012
            for axis, delta in enumerate((dx, dy)):
                force[a][axis] += delta/distance*pull
                force[b][axis] -= delta/distance*pull
        cooling = 1-step/220
        for uid, point in points.items():
            for axis in (0, 1):
                point[axis] += max(-4, min(4, force[uid][axis]))*cooling
        # Project entire avatar/name boxes apart, not just the avatar circles.
        for _ in range(4):
            for i, a in enumerate(ids):
                for b in ids[i+1:]:
                    dx, dy = points[b][0]-points[a][0], points[b][1]-points[a][1]
                    overlap_x, overlap_y = 208-abs(dx), 142-abs(dy)
                    if overlap_x > 0 and overlap_y > 0:
                        axis = 0 if overlap_x < overlap_y else 1
                        shift = ((overlap_x if axis == 0 else overlap_y)+.5)/2
                        sign = 1 if (dx if axis == 0 else dy) >= 0 else -1
                        points[a][axis] -= shift*sign
                        points[b][axis] += shift*sign
            for point in points.values():
                point[0] = max(110, min(890, point[0]))
                point[1] = max(60, min(height-105, point[1]))
    overlaps = any(abs(points[a][0]-points[b][0]) < 207 and abs(points[a][1]-points[b][1]) < 141
                   for i, a in enumerate(ids) for b in ids[i+1:])
    if overlaps:
        # Bounded packing fallback for unusually dense or disconnected graphs.
        rows = math.ceil(count/4)
        columns = math.ceil(count/rows)
        for row in range(rows):
            row_ids = ids[row*columns:(row+1)*columns]
            for col, uid in enumerate(row_ids):
                points[uid] = [500+(col-(len(row_ids)-1)/2)*240, 80+row*180]
    return {uid: tuple(round(v, 3) for v in point) for uid, point in points.items()}, height


def curve_point(start, control, end, t):
    return tuple((1-t)**2*start[i]+2*(1-t)*t*control[i]+t*t*end[i] for i in (0, 1))


def box_hits(point, half_width, positions, name_boxes=()):
    x, y = point
    return (sum(math.hypot(max(0, abs(x-p[0])-half_width), max(0, abs(y-p[1])-14)) < 38 for p in positions)
            + sum(abs(x-bx) < half_width+bw/2+4 and abs(y-by) < 14+bh/2+4 for bx,by,bw,bh in name_boxes))


def route_link(start, end, positions: dict, height: int, *, half_width=0, labels=(), name_boxes=()):
    """Labels may slide along a gentle arc; they never pull a link off course."""
    dx, dy = end[0]-start[0], end[1]-start[1]
    distance = max(1, math.hypot(dx, dy))
    middle = ((start[0]+end[0])/2, (start[1]+end[1])/2)
    obstacles = [p for p in positions.values() if p != start and p != end]
    candidates = []
    for bow in (0, 28, -28, 56, -56):
        control = (middle[0]-dy/distance*bow, middle[1]+dx/distance*bow)
        hits = sum(box_hits(curve_point(start, control, end, t/20), 1, obstacles, name_boxes) for t in range(2, 19))
        for t in (.5, .4, .6, .3, .7, .25, .75, .2, .8):
            label = curve_point(start, control, end, t)
            outside = not half_width+8 <= label[0] <= 992-half_width or not 18 <= label[1] <= height-18
            collisions = sum(abs(label[0]-x) < half_width+w+8 and abs(label[1]-y) < 32 for x, y, w in labels)
            label_hits = box_hits(label, half_width, positions.values(), name_boxes) if half_width else 0
            score = hits*800 + label_hits*3000 + collisions*4000 + outside*10000 + abs(t-.5)*30 + abs(bow)*.04
            candidates.append((score, control, label, t))
    _, control, label, t = min(candidates, key=lambda c: c[0])
    path = f'M {start[0]} {start[1]} Q {control[0]:.3f} {control[1]:.3f} {end[0]} {end[1]}'
    return {"path": path, "start": start, "control": control, "end": end, "label": label, "t": t}
