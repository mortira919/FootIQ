"""Single-game Glicko-2 updates (Mark Glickman).

Display ratings stay on the usual scale. Internally they are shifted by the
standard factor 173.7178 around 1500, so a displayed 800 maps below the
Glicko-2 origin on purpose.
"""

import math

SCALE = 173.7178
TAU = 0.5
EPSILON = 1e-6

START_R = 800
START_RD = 350
START_SIGMA = 0.06
OPPONENT_RD = 80

_EXP_CLAMP = 50.0


def puzzle_rating(difficulty: float) -> float:
    """Puzzle strength on the display scale: 700 + 100 * difficulty."""
    return 700 + 100 * difficulty


def _to_mu(rating: float) -> float:
    return (rating - 1500.0) / SCALE


def _to_phi(rd: float) -> float:
    return rd / SCALE


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + (3.0 * phi * phi) / (math.pi * math.pi))


def _expected(mu: float, mu_j: float, g_phi: float) -> float:
    x = g_phi * (mu - mu_j)
    if x > _EXP_CLAMP:
        return 1.0
    if x < -_EXP_CLAMP:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _new_sigma(phi: float, sigma: float, delta: float, v: float) -> float:
    """Illinois algorithm root of Glickman's volatility function. tau = 0.5."""
    phi2 = phi * phi
    delta2 = delta * delta
    log_sigma2 = math.log(sigma * sigma)
    tau2 = TAU * TAU

    def f(x: float) -> float:
        ex = math.exp(x)
        base = phi2 + v + ex
        return (ex * (delta2 - base)) / (2.0 * base * base) - (x - log_sigma2) / tau2

    big_a = log_sigma2
    margin = delta2 - phi2 - v
    if margin > 0.0:
        big_b = math.log(margin)
    else:
        k = 1
        while f(log_sigma2 - k * TAU) < 0.0 and k < 200:
            k += 1
        big_b = log_sigma2 - k * TAU

    f_a = f(big_a)
    f_b = f(big_b)
    for _ in range(100):
        if abs(big_b - big_a) <= EPSILON:
            break
        gap = f_b - f_a
        if gap == 0.0:
            break
        big_c = big_a + (big_a - big_b) * f_a / gap
        f_c = f(big_c)
        if f_c * f_b < 0.0:
            big_a = big_b
            f_a = f_b
        else:
            f_a *= 0.5
        big_b = big_c
        f_b = f_c
    return math.exp(big_a / 2.0)


def update_rating(
    r: float,
    rd: float,
    sigma: float,
    opponent_rating: float,
    score: float,
) -> tuple[float, float, float, int]:
    """Apply one Glicko-2 game against a puzzle.

    The opponent rating deviation is fixed at 80. ``score`` is 1 gold,
    0.5 silver, 0 error, or a video fraction in ``[0, 1]``.

    Returns ``(new_r, new_rd, new_sigma, delta)`` with ``delta = round(new_r - r)``.
    """
    mu = _to_mu(r)
    phi = _to_phi(rd)
    mu_j = _to_mu(opponent_rating)
    phi_j = _to_phi(OPPONENT_RD)

    g_phi = _g(phi_j)
    expected = _expected(mu, mu_j, g_phi)
    variance_term = g_phi * g_phi * expected * (1.0 - expected)
    if variance_term < 1e-12:
        variance_term = 1e-12
    outcome_term = g_phi * (score - expected)

    v = 1.0 / variance_term
    delta_mu = v * outcome_term
    new_sigma = _new_sigma(phi, sigma, delta_mu, v)

    phi_star = math.sqrt(phi * phi + new_sigma * new_sigma)
    new_phi = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)
    new_mu = mu + new_phi * new_phi * outcome_term

    new_r = SCALE * new_mu + 1500.0
    new_rd = SCALE * new_phi
    return new_r, new_rd, new_sigma, round(new_r - r)
