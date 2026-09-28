import copy
import math

PITCH_W = 68.0
PITCH_H = 105.0
COS_30 = math.cos(math.radians(30))


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def mirror_puzzle(puzzle: dict) -> dict:
    mirrored = copy.deepcopy(puzzle)
    scene = mirrored["scene_data"]
    for group in ("mates", "opps"):
        for player in scene[group]:
            player["path"] = [[PITCH_W - x, y] for x, y in player["path"]]
    mirrored["optimal_zone_polygon"] = [
        [PITCH_W - x, y] for x, y in mirrored["optimal_zone_polygon"]
    ]
    return mirrored


def _last(player: dict) -> tuple[float, float]:
    x, y = player["path"][-1]
    return float(x), float(y)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _mul(a, k):
    return (a[0] * k, a[1] * k)


def _len(v) -> float:
    return math.hypot(v[0], v[1])


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def scene_snapshot(puzzle: dict) -> dict:
    scene = puzzle["scene_data"]
    mates = [_last(player) for player in scene["mates"]]
    opps = [_last(player) for player in scene["opps"]]
    passer = scene["ball"][-1]
    ball = (mates[passer][0], mates[passer][1] - 2)
    return {
        "me": scene["me"],
        "passer": passer,
        "mates": mates,
        "opps": opps,
        "ball": ball,
        "pass_mode": passer == scene["me"],
    }


def _shadow_polygon(ball, opp):
    d = _sub(opp, ball)
    length = _len(d)
    if length < 1:
        return None
    n = _mul((-d[1] / length, d[0] / length), 1.5)
    a = _add(opp, n)
    b = _sub(opp, n)
    k = (length + 40) / length
    return [a, b, _add(ball, _mul(_sub(b, ball), k)), _add(ball, _mul(_sub(a, ball), k))]


def _cone_hit(ball, target, opp):
    to_target = _sub(target, ball)
    travel = _len(to_target)
    if travel <= 2:
        return None
    direction = _sub(ball, opp)
    direction_len = _len(direction)
    if direction_len == 0:
        return None
    direction = (direction[0] / direction_len, direction[1] / direction_len)
    radius = min(6.0, max(3.0, 3 + 0.1 * _dist(opp, ball)))
    step = (to_target[0] / travel, to_target[1] / travel)
    distance = 2.0
    while distance < travel - 1e-9:
        point = _add(ball, _mul(step, distance))
        if _cone_contains(point, opp, direction, radius):
            return distance, point
        distance += 0.5
    if _cone_contains(target, opp, direction, radius):
        return travel, target
    return None


def _cone_contains(point, opp, direction, radius) -> bool:
    offset = _sub(point, opp)
    distance = _len(offset)
    if distance < 0.01:
        return True
    if distance > radius:
        return False
    cosine = (offset[0] * direction[0] + offset[1] * direction[1]) / distance
    return cosine >= COS_30


def _interception(ball, target, opp):
    shadow = _shadow_polygon(ball, opp)
    if shadow is not None and point_in_polygon(target[0], target[1], shadow):
        return _dist(ball, opp), "shadow"
    cone = _cone_hit(ball, target, opp)
    if cone is not None:
        return cone[0], "cone"
    if _dist(opp, target) < 2:
        return _dist(target, ball), "marked"
    return None


def judge(puzzle: dict, target, mirrored: bool = False) -> dict:
    scene_puzzle = mirror_puzzle(puzzle) if mirrored else puzzle
    snap = scene_snapshot(scene_puzzle)
    if target is None:
        return _result("error", "timeout", None)
    t = (float(target[0]), float(target[1]))
    if not (0 <= t[0] <= PITCH_W and 0 <= t[1] <= PITCH_H):
        return _result("error", "out", None)
    if snap["pass_mode"]:
        others = [index for index in range(len(snap["mates"])) if index != snap["passer"]]
        if not others:
            return _result("error", "noReceiver", None)
        receiver = min(others, key=lambda index: _dist(snap["mates"][index], t))
    else:
        receiver = snap["me"]
    if _dist(snap["mates"][receiver], t) > 15:
        return _result("error", "noReceiver", None)
    opp_ys = sorted(pos[1] for pos in snap["opps"])
    offside_line = opp_ys[1] if len(opp_ys) >= 2 else 0
    receiver_y = snap["mates"][receiver][1]
    if receiver_y < 52.5 and receiver_y < snap["ball"][1] and receiver_y < offside_line:
        return _result("error", "offside", None)
    best = None
    best_index = None
    for index, opp in enumerate(snap["opps"]):
        hit = _interception(snap["ball"], t, opp)
        if hit is not None and (best is None or hit[0] < best[0]):
            best = hit
            best_index = index
    if best is not None:
        number = scene_puzzle["scene_data"]["opps"][best_index]["number"]
        return _result("error", best[1], number)
    if point_in_polygon(t[0], t[1], scene_puzzle["optimal_zone_polygon"]):
        return _result("gold", "optimal", None)
    return _result("silver", "safe", None)


def _result(outcome: str, reason: str, culprit) -> dict:
    return {"outcome": outcome, "reason": reason, "culprit_number": culprit}


def gold_centroid(puzzle: dict) -> tuple[float, float]:
    polygon = puzzle["optimal_zone_polygon"]
    return (
        sum(point[0] for point in polygon) / len(polygon),
        sum(point[1] for point in polygon) / len(polygon),
    )
