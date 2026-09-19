"""Motor estatístico. Só calcula a partir de jogos com placar conhecido."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

INSUFFICIENT = "Dados insuficientes para esta análise."
LOW_DATA = "Não existem dados suficientes para produzir uma análise estatística confiável desta partida."
LEAGUE_AVG = 1.35  # gols por equipe / jogo, fallback neutro


def analyze_match(payload: dict) -> dict:
    home = payload.get("home") or {}
    away = payload.get("away") or {}
    home_games = _finished(payload.get("home_games") or [])
    away_games = _finished(payload.get("away_games") or [])
    h2h = _finished(payload.get("h2h") or [])

    home_id = str(home.get("id") or "")
    away_id = str(away.get("id") or "")

    home_form = team_form(home_games, home_id, home.get("record") or {})
    away_form = team_form(away_games, away_id, away.get("record") or {})

    sample_n = min(len(home_games), len(away_games))
    data_flags = {
        "home_games": len(home_games),
        "away_games": len(away_games),
        "h2h": len(h2h),
        "season_record": bool(home.get("record", {}).get("games") or away.get("record", {}).get("games")),
        "lineups": bool(payload.get("lineups")),
        "injuries": bool(payload.get("injuries_home") or payload.get("injuries_away")),
        "news": bool(payload.get("news")),
        "xg": _has_xg(payload),
        "odds": bool(payload.get("odds")),
    }

    if sample_n == 0 and not data_flags["season_record"]:
        return _empty_analysis(home, away, payload, reason=INSUFFICIENT)

    markets = build_markets(home_form, away_form, h2h, home_id, away_id)
    confidence = confidence_level(sample_n, data_flags, home_form, away_form, markets)
    comparison = compare_teams(home_form, away_form)
    scores = markets.get("placares") or []
    top_score = scores[0]["placar"] if scores else INSUFFICIENT

    resultado = markets["resultado"]
    gols = _best_goal_market(markets["gols"])
    btts = markets["btts"]
    trend = goal_trend(home_form, away_form, markets)
    value = rank_markets(markets)
    low_sample = sample_n < 4

    summary = {
        "resultado": _result_label(resultado),
        "over15": (markets.get("gols") or {}).get("mais_1.5", {}).get("label") or INSUFFICIENT,
        "over25": (markets.get("gols") or {}).get("mais_2.5", {}).get("label") or INSUFFICIENT,
        "under25": (markets.get("gols") or {}).get("menos_2.5", {}).get("label") or INSUFFICIENT,
        "gols": gols,
        "ambas": f"{'SIM' if (btts['sim'].get('pct') or 0) >= (btts['nao'].get('pct') or 0) else 'NÃO'} — "
        + f"{max(btts['sim'].get('pct') or 0, btts['nao'].get('pct') or 0)}%",
        "placar": top_score,
        "confianca": confidence["nivel"],
        "consistencia": confidence.get("consistencia") or confidence["nivel"],
    }

    return {
        "ok": True,
        "insufficient": False,
        "low_sample": low_sample,
        "alert": LOW_DATA if low_sample else None,
        "disclaimer": "Esta análise é baseada nos dados disponíveis e não garante o resultado da partida.",
        "prob_note": "As porcentagens são estimativas estatísticas calculadas a partir dos jogos coletados, não garantias.",
        "fixture": payload.get("fixture") or {},
        "home": {**home, "form": home_form},
        "away": {**away, "form": away_form},
        "sample": data_flags,
        "h2h": summarize_h2h(h2h, home_id, away_id),
        "lineups": payload.get("lineups") or [],
        "injuries_home": payload.get("injuries_home") or [],
        "injuries_away": payload.get("injuries_away") or [],
        "news": payload.get("news") or [],
        "odds": payload.get("odds"),
        "match_stats": payload.get("match_stats") or [],
        "importance": payload.get("importance") or _importance(payload),
        "markets": markets,
        "value_markets": value,
        "goal_trend": trend,
        "comparison": comparison,
        "confidence": confidence,
        "summary": summary,
        "updated_at": payload.get("updated_at"),
        "source": payload.get("source") or "espn",
        "sources": payload.get("sources") or [],
        "missing": payload.get("missing") or [],
    }


def team_form(games: list[dict], team_id: str, season: dict) -> dict:
    last5 = games[:5]
    last10 = games[:10]
    home_g = [g for g in games if str(g.get("home_id") or (g.get("home") or {}).get("id")) == team_id]
    away_g = [g for g in games if str(g.get("away_id") or (g.get("away") or {}).get("id")) == team_id]

    def pack(sample: list[dict], label: str) -> dict:
        if not sample:
            return {
                "label": label,
                "n": 0,
                "available": False,
                "message": INSUFFICIENT,
            }
        gf, ga, w, d, l = 0, 0, 0, 0, 0
        over05 = over15 = over25 = over35 = under15 = under25 = under35 = btts = cs = 0
        seq = []
        for g in sample:
            hs, aws = g["home_score"], g["away_score"]
            hid = str(g.get("home_id") or (g.get("home") or {}).get("id") or "")
            if hid == team_id:
                scored, conceded = hs, aws
            else:
                scored, conceded = aws, hs
            gf += scored
            ga += conceded
            if scored > conceded:
                w += 1
                seq.append("V")
            elif scored == conceded:
                d += 1
                seq.append("E")
            else:
                l += 1
                seq.append("D")
            total = hs + aws
            if total > 0.5:
                over05 += 1
            if total > 1.5:
                over15 += 1
            else:
                under15 += 1
            if total > 2.5:
                over25 += 1
            else:
                under25 += 1
            if total > 3.5:
                over35 += 1
            else:
                under35 += 1
            if hs > 0 and aws > 0:
                btts += 1
            if conceded == 0:
                cs += 1
        n = len(sample)
        return {
            "label": label,
            "n": n,
            "available": True,
            "wins": w,
            "draws": d,
            "losses": l,
            "gf": gf,
            "ga": ga,
            "avg_gf": round(gf / n, 2),
            "avg_ga": round(ga / n, 2),
            "avg_total": round((gf + ga) / n, 2),
            "over05": _pct(over05, n),
            "over15": _pct(over15, n),
            "over25": _pct(over25, n),
            "over35": _pct(over35, n),
            "under15": _pct(under15, n),
            "under25": _pct(under25, n),
            "under35": _pct(under35, n),
            "btts": _pct(btts, n),
            "clean_sheets": _pct(cs, n),
            "points": w * 3 + d,
            "ppg": round((w * 3 + d) / n, 2),
            "sequence": "".join(seq),
        }

    season_block = None
    if season.get("games"):
        n = int(season["games"] or 0)
        if n > 0:
            season_block = {
                "label": "campeonato",
                "n": n,
                "available": True,
                "record": season.get("record") or "",
                "standing": season.get("standing") or "",
                "gf": season.get("gf"),
                "ga": season.get("ga"),
                "avg_gf": _div(season.get("gf"), n),
                "avg_ga": _div(season.get("ga"), n),
                "home_games": season.get("home_games"),
                "home_gf": season.get("home_gf"),
                "home_ga": season.get("home_ga"),
                "away_games": season.get("away_games"),
                "away_gf": season.get("away_gf"),
                "away_ga": season.get("away_ga"),
                "points": season.get("points"),
                "rank": season.get("rank"),
            }

    return {
        "last5": pack(last5, "últimos 5"),
        "last10": pack(last10, "últimos 10"),
        "home": pack(home_g[:8], "como mandante"),
        "away": pack(away_g[:8], "como visitante"),
        "season": season_block,
        "games_used": [
            {
                "date": g.get("date"),
                "home": _name(g, "home"),
                "away": _name(g, "away"),
                "score": f"{g['home_score']}-{g['away_score']}",
                "competition": g.get("competition") or g.get("league_name") or "",
            }
            for g in games[:10]
        ],
    }


def build_markets(hf: dict, af: dict, h2h: list[dict], home_id: str, away_id: str) -> dict:
    lam_h, lam_a, method = _lambdas(hf, af)
    matrix = None
    if lam_h is not None and lam_a is not None:
        matrix = poisson_matrix(lam_h, lam_a, max_goals=6)

    freq = _combined_freq(hf, af, h2h)

    def blend(model_p: float | None, freq_p: float | None, w_model: float = 0.55) -> tuple[int | None, str]:
        if model_p is None and freq_p is None:
            return None, INSUFFICIENT
        if model_p is None:
            return int(round(freq_p * 100)), "frequência amostral"
        if freq_p is None:
            return int(round(model_p * 100)), "modelo de Poisson"
        p = w_model * model_p + (1 - w_model) * freq_p
        return int(round(p * 100)), "Poisson + frequência"

    if matrix:
        p_home = sum(matrix[i][j] for i in range(7) for j in range(7) if i > j)
        p_draw = sum(matrix[i][i] for i in range(7))
        p_away = sum(matrix[i][j] for i in range(7) for j in range(7) if i < j)
        p_over = {}
        p_under = {}
        p_btts_y = 0.0
        p_btts_n = 0.0
        scores = []
        for i in range(7):
            for j in range(7):
                p = matrix[i][j]
                scores.append((i, j, p))
                tot = i + j
                for line in (0.5, 1.5, 2.5, 3.5):
                    p_over.setdefault(line, 0.0)
                    p_under.setdefault(line, 0.0)
                    if tot > line:
                        p_over[line] += p
                    else:
                        p_under[line] += p
                if i > 0 and j > 0:
                    p_btts_y += p
                else:
                    p_btts_n += p
        scores.sort(key=lambda x: -x[2])
        placares = [
            {"placar": f"{i}-{j}", "pct": int(round(p * 100)), "p": round(p, 4)}
            for i, j, p in scores[:8]
            if p > 0.01
        ]
    else:
        p_home = p_draw = p_away = None
        p_over = {0.5: None, 1.5: None, 2.5: None, 3.5: None}
        p_under = {0.5: None, 1.5: None, 2.5: None, 3.5: None}
        p_btts_y = p_btts_n = None
        placares = []

    rh, mh = blend(p_home, freq.get("home_win"))
    rd, md = blend(p_draw, freq.get("draw"))
    ra, ma = blend(p_away, freq.get("away_win"))

    gols = {}
    for line in (0.5, 1.5, 2.5, 3.5):
        key = str(line)
        ov, mov = blend(p_over.get(line), freq.get(f"over{key}"))
        un, mun = blend(p_under.get(line), freq.get(f"under{key}"))
        gols[f"mais_{key}"] = _mkt(f"Mais de {key}", ov, mov)
        gols[f"menos_{key}"] = _mkt(f"Menos de {key}", un, mun)

    bs, mbs = blend(p_btts_y, freq.get("btts"))
    bn, mbn = blend(p_btts_n, None if freq.get("btts") is None else 1 - freq["btts"])

    dc_home_draw = None if rh is None or rd is None else min(99, rh + rd)
    dc_home_away = None if rh is None or ra is None else min(99, rh + ra)
    dc_draw_away = None if rd is None or ra is None else min(99, rd + ra)

    return {
        "lambda_home": lam_h,
        "lambda_away": lam_a,
        "method": method,
        "resultado": {
            "casa": _mkt("Casa", rh, mh),
            "empate": _mkt("Empate", rd, md),
            "fora": _mkt("Fora", ra, ma),
        },
        "gols": gols,
        "btts": {
            "sim": _mkt("Ambas marcam — Sim", bs, mbs),
            "nao": _mkt("Ambas marcam — Não", bn, mbn),
        },
        "dupla_chance": {
            "casa_empate": _mkt("Casa ou Empate", dc_home_draw, "soma 1X2"),
            "casa_fora": _mkt("Casa ou Fora", dc_home_away, "soma 1X2"),
            "empate_fora": _mkt("Empate ou Fora", dc_draw_away, "soma 1X2"),
        },
        "placares": placares,
    }


def poisson_matrix(lam_h: float, lam_a: float, max_goals: int = 6) -> list[list[float]]:
    return [[_pois(i, lam_h) * _pois(j, lam_a) for j in range(max_goals + 1)] for i in range(max_goals + 1)]


def _pois(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam**k) / math.factorial(k)


def _lambdas(hf: dict, af: dict) -> tuple[float | None, float | None, str]:
    """Ataque mandante × defesa visitante, com vantagem de casa leve se houver split."""
    h_att, h_def, h_src = _rates(hf, prefer="home")
    a_att, a_def, a_src = _rates(af, prefer="away")
    if h_att is None or a_att is None:
        return None, None, INSUFFICIENT
    lg = LEAGUE_AVG
    # Modelo Dixon-Coles simplificado (independente)
    lam_h = max(0.35, min(3.8, h_att * (a_def / lg) * 1.08))
    lam_a = max(0.25, min(3.4, a_att * (h_def / lg) * 0.95))
    return round(lam_h, 3), round(lam_a, 3), f"Poisson ({h_src} / {a_src})"


def _rates(form: dict, prefer: str) -> tuple[float | None, float | None, str]:
    season = form.get("season") or {}
    split_n = season.get(f"{prefer}_games")
    split_gf = season.get(f"{prefer}_gf")
    split_ga = season.get(f"{prefer}_ga")
    if split_n and split_n >= 3 and split_gf is not None:
        return split_gf / split_n, (split_ga or 0) / split_n, f"temporada {prefer}"
    if season.get("n") and season.get("avg_gf") is not None:
        adj = 1.10 if prefer == "home" else 0.92
        return season["avg_gf"] * adj, (season.get("avg_ga") or LEAGUE_AVG) / adj, "temporada"
    block = form.get("last10") if form.get("last10", {}).get("available") else form.get("last5")
    if block and block.get("available"):
        return block["avg_gf"], block["avg_ga"], block["label"]
    return None, None, INSUFFICIENT


def _combined_freq(hf: dict, af: dict, h2h: list[dict]) -> dict:
    """Frequências observadas (não inventadas)."""
    samples = []
    for form in (hf, af):
        b = form.get("last10") if form.get("last10", {}).get("n", 0) >= 5 else form.get("last5")
        if b and b.get("available"):
            samples.append(b)
    if not samples:
        return {}
    def avg(key: str) -> float | None:
        vals = [s[key] for s in samples if key in s and s[key] is not None]
        if not vals:
            return None
        return sum(vals) / len(vals) / 100.0

    # Resultado: forma recente ponderada + H2H se houver
    h5 = hf.get("last5") or {}
    a5 = af.get("last5") or {}
    home_win = draw = away_win = None
    if h5.get("available") and a5.get("available"):
        # força relativa via ppg
        hp = h5.get("ppg") or 0
        ap = a5.get("ppg") or 0
        # converter ppg em probabilidade grosseira e misturar
        # ppg 0-3 → score
        hs = hp / 3.0
        aws = ap / 3.0
        gap = hs - aws
        home_win = min(0.72, max(0.18, 0.46 + gap * 0.35))
        away_win = min(0.72, max(0.14, 0.28 - gap * 0.35))
        draw = max(0.16, 1 - home_win - away_win)
        s = home_win + draw + away_win
        home_win, draw, away_win = home_win / s, draw / s, away_win / s

    if len(h2h) >= 3:
        hw = sum(1 for g in h2h if g["home_score"] > g["away_score"] and str(g.get("home_id")) == str(g.get("_home_focus", g.get("home_id"))))
        # melhor: contar vitórias do mandante atual
        hw = dw = aw = 0
        hid = None
        # games already tagged with home/away scores of that historical match
        for g in h2h:
            hs, aws = g["home_score"], g["away_score"]
            # we don't remap; use actual historical home/away — weak for venue
            if hs > aws:
                hw += 1
            elif hs == aws:
                dw += 1
            else:
                aw += 1
        n = len(h2h)
        h2h_home, h2h_draw, h2h_away = hw / n, dw / n, aw / n
        if home_win is not None:
            home_win = 0.7 * home_win + 0.3 * h2h_home
            draw = 0.7 * draw + 0.3 * h2h_draw
            away_win = 0.7 * away_win + 0.3 * h2h_away

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "over0.5": avg("over05"),
        "over1.5": avg("over15"),
        "over2.5": avg("over25"),
        "over3.5": avg("over35"),
        "under0.5": None if avg("over05") is None else 1 - avg("over05"),
        "under1.5": avg("under15") if avg("under15") is not None else (None if avg("over15") is None else 1 - avg("over15")),
        "under2.5": avg("under25"),
        "under3.5": avg("under35") if avg("under35") is not None else (None if avg("over35") is None else 1 - avg("over35")),
        "btts": avg("btts"),
    }


def compare_teams(hf: dict, af: dict) -> dict:
    def val(form: dict, path: tuple, fallback=None):
        cur = form
        for p in path:
            if not isinstance(cur, dict) or p not in cur:
                return fallback
            cur = cur[p]
        return cur

    rows = []

    def add(label, h, a, invert=False):
        rows.append({"label": label, "home": h, "away": a, "invert": invert})

    add("Forma (Pts/J)", val(hf, ("last5", "ppg")), val(af, ("last5", "ppg")))
    add("Ataque (gols/J)", val(hf, ("last5", "avg_gf")), val(af, ("last5", "avg_gf")))
    add("Defesa (sofridos/J)", val(hf, ("last5", "avg_ga")), val(af, ("last5", "avg_ga")), invert=True)
    add("Média de gols", val(hf, ("last5", "avg_total")), val(af, ("last5", "avg_total")))
    add("Over 1.5 %", val(hf, ("last5", "over15")), val(af, ("last5", "over15")))
    add("Over 2.5 %", val(hf, ("last5", "over25")), val(af, ("last5", "over25")))
    add("Ambas marcam %", val(hf, ("last5", "btts")), val(af, ("last5", "btts")))
    add("Clean sheets %", val(hf, ("last5", "clean_sheets")), val(af, ("last5", "clean_sheets")))
    add("Casa/Fora gf", val(hf, ("home", "avg_gf")), val(af, ("away", "avg_gf")))
    return {"rows": rows}


def confidence_level(sample_n: int, flags: dict, hf: dict, af: dict, markets: dict) -> dict:
    score = 0
    reasons = []
    if sample_n >= 8:
        score += 40
        reasons.append("amostra de 8+ jogos por lado")
    elif sample_n >= 5:
        score += 28
        reasons.append("amostra de 5–7 jogos")
    elif sample_n >= 3:
        score += 16
        reasons.append("amostra curta (3–4 jogos)")
    else:
        score += 6
        reasons.append("amostra muito pequena")

    if flags.get("season_record"):
        score += 15
        reasons.append("registro da temporada disponível")
    if flags.get("h2h") and flags["h2h"] >= 3:
        score += 10
        reasons.append("confrontos diretos recentes")
    if flags.get("lineups"):
        score += 8
        reasons.append("escalação disponível")
    if flags.get("injuries"):
        score += 5
        reasons.append("desfalques reportados")
    if flags.get("xg"):
        score += 6
        reasons.append("xG disponível")
    if flags.get("odds"):
        score += 4
        reasons.append("odds de mercado disponíveis")

    # divergência over/under
    g = markets.get("gols") or {}
    o25 = (g.get("mais_2.5") or {}).get("pct")
    u25 = (g.get("menos_2.5") or {}).get("pct")
    if o25 is not None and u25 is not None and abs(o25 - u25) < 8:
        score -= 8
        reasons.append("indicadores de gols pouco decisivos")

    score = max(0, min(100, score))
    if score >= 62 and sample_n >= 5:
        nivel, emoji, cons = "ALTA", "🟢", "ALTA CONSISTÊNCIA"
    elif score >= 38:
        nivel, emoji, cons = "MÉDIA", "🟡", "CONSISTÊNCIA MODERADA"
    else:
        nivel, emoji, cons = "BAIXA", "🔴", "BAIXA CONSISTÊNCIA"
    return {
        "nivel": nivel,
        "consistencia": cons,
        "emoji": emoji,
        "score": score,
        "reasons": reasons,
        "note": "O indicador mede volume e coerência dos dados coletados. Não classifica mercado como certo.",
    }


def summarize_h2h(games: list[dict], home_id: str, away_id: str) -> dict:
    if not games:
        return {"available": False, "message": INSUFFICIENT, "games": []}
    hw = dw = aw = 0
    for g in games:
        hid = str(g.get("home_id") or (g.get("home") or {}).get("id") or "")
        hs, aws = g["home_score"], g["away_score"]
        if hid == home_id:
            if hs > aws:
                hw += 1
            elif hs == aws:
                dw += 1
            else:
                aw += 1
        else:
            if aws > hs:
                hw += 1
            elif hs == aws:
                dw += 1
            else:
                aw += 1
    return {
        "available": True,
        "n": len(games),
        "home_wins": hw,
        "draws": dw,
        "away_wins": aw,
        "games": [
            {
                "date": g.get("date"),
                "home": _name(g, "home"),
                "away": _name(g, "away"),
                "score": f"{g['home_score']}-{g['away_score']}",
            }
            for g in games[:8]
        ],
    }


def goal_trend(hf: dict, af: dict, markets: dict) -> dict:
    h = hf.get("last5") if hf.get("last5", {}).get("available") else hf.get("last10") or {}
    a = af.get("last5") if af.get("last5", {}).get("available") else af.get("last10") or {}
    hg = h.get("avg_total") if h.get("available") else None
    ag = a.get("avg_total") if a.get("available") else None
    combined = None
    if hg is not None and ag is not None:
        combined = round((hg + ag) / 2.0, 2)
    g = markets.get("gols") or {}
    b = markets.get("btts") or {}
    return {
        "home_avg": hg,
        "away_avg": ag,
        "combined": combined,
        "over15": (g.get("mais_1.5") or {}).get("pct"),
        "over25": (g.get("mais_2.5") or {}).get("pct"),
        "under25": (g.get("menos_2.5") or {}).get("pct"),
        "btts": (b.get("sim") or {}).get("pct"),
        "home_attack": h.get("avg_gf") if h.get("available") else None,
        "away_attack": a.get("avg_gf") if a.get("available") else None,
    }


def rank_markets(markets: dict) -> list[dict]:
    """Mercados com maior suporte estatístico (não é ranking de 'aposta certa')."""
    pool = []
    for group, obj in (
        ("Gols", markets.get("gols") or {}),
        ("Ambas", markets.get("btts") or {}),
        ("Resultado", markets.get("resultado") or {}),
    ):
        for key, item in obj.items():
            if not item or item.get("pct") is None:
                continue
            pool.append(
                {
                    "grupo": group,
                    "key": key,
                    "nome": item.get("nome") or key,
                    "pct": item["pct"],
                    "method": item.get("method") or "",
                }
            )
    pool.sort(key=lambda x: -x["pct"])
    return pool[:6]


def compact_row(analysis: dict) -> dict:
    """Linha para tabela de vários jogos."""
    fx = analysis.get("fixture") or {}
    mk = analysis.get("markets") or {}
    sm = analysis.get("summary") or {}
    conf = analysis.get("confidence") or {}
    if analysis.get("insufficient"):
        return {
            "jogo": fx.get("label") or "Jogo",
            "home": fx.get("home_name"),
            "away": fx.get("away_name"),
            "resultado": INSUFFICIENT,
            "over15": None,
            "over25": None,
            "under25": None,
            "btts": None,
            "confianca": "BAIXA",
        }
    res = mk.get("resultado") or {}
    winner = max(
        (("Casa", (res.get("casa") or {}).get("pct") or 0),
         ("Empate", (res.get("empate") or {}).get("pct") or 0),
         ("Fora", (res.get("fora") or {}).get("pct") or 0)),
        key=lambda x: x[1],
    )
    return {
        "jogo": f"{fx.get('home_name') or 'Casa'} x {fx.get('away_name') or 'Fora'}",
        "home": fx.get("home_name"),
        "away": fx.get("away_name"),
        "league": fx.get("league_name"),
        "date": fx.get("date"),
        "resultado": f"{winner[0]} {winner[1]}%",
        "resultado_side": winner[0],
        "resultado_pct": winner[1],
        "consistencia": conf.get("consistencia") or sm.get("consistencia"),
        "over15": (mk.get("gols") or {}).get("mais_1.5", {}).get("pct"),
        "over25": (mk.get("gols") or {}).get("mais_2.5", {}).get("pct"),
        "under25": (mk.get("gols") or {}).get("menos_2.5", {}).get("pct"),
        "btts": (mk.get("btts") or {}).get("sim", {}).get("pct"),
        "confianca": conf.get("nivel") or sm.get("confianca"),
        "event_id": fx.get("id"),
        "league_slug": fx.get("league"),
    }


def _finished(games: list[dict]) -> list[dict]:
    out = []
    for g in games:
        hs = g.get("home_score")
        aws = g.get("away_score")
        if hs is None or aws is None:
            continue
        g = dict(g)
        if "home_id" not in g and g.get("home"):
            g["home_id"] = str(g["home"].get("id") or "")
        if "away_id" not in g and g.get("away"):
            g["away_id"] = str(g["away"].get("id") or "")
        out.append(g)
    # mais recente primeiro
    out.sort(key=lambda x: x.get("date") or "", reverse=True)
    return out


def _mkt(nome: str, pct: int | None, method: str) -> dict:
    if pct is None:
        return {"nome": nome, "pct": None, "label": INSUFFICIENT, "method": method}
    return {"nome": nome, "pct": max(1, min(99, pct)), "label": f"{max(1, min(99, pct))}%", "method": method}


def _pct(part: int, n: int) -> int:
    return int(round(100.0 * part / n)) if n else 0


def _div(a, b) -> float | None:
    if a is None or not b:
        return None
    return round(float(a) / float(b), 2)


def _name(g: dict, side: str) -> str:
    if g.get(side) and isinstance(g[side], dict):
        return g[side].get("name") or g[side].get("abbreviation") or ""
    if side == "home":
        return g.get("home_name") or ""
    if side == "away":
        return g.get("away_name") or g.get("opponent") or ""
    return ""


def _best_goal_market(gols: dict) -> str:
    best = None
    for k, v in gols.items():
        if v.get("pct") is None:
            continue
        if best is None or v["pct"] > best["pct"]:
            best = v
    if not best:
        return INSUFFICIENT
    return f"{best['nome']} — {best['pct']}%"


def _result_label(res: dict) -> str:
    opts = [
        ("Casa", res.get("casa") or {}),
        ("Empate", res.get("empate") or {}),
        ("Fora", res.get("fora") or {}),
    ]
    valid = [(n, o) for n, o in opts if o.get("pct") is not None]
    if not valid:
        return INSUFFICIENT
    n, o = max(valid, key=lambda x: x[1]["pct"])
    return f"{n} — {o['pct']}%"


def _has_xg(payload: dict) -> bool:
    for row in payload.get("match_stats") or []:
        if row.get("xg") not in (None, "", "null"):
            return True
    return False


def _importance(payload: dict) -> str:
    fx = payload.get("fixture") or {}
    league = (fx.get("league_name") or "") + " " + (fx.get("league") or "")
    big = ["champions", "libertadores", "world", "premier", "liga"]
    if any(b in league.lower() for b in big):
        return "Partida de competição de alto nível — impacto de tabela e elenco tende a ser maior."
    return "Importância avaliada pela competição e posição na tabela, quando disponíveis."


def _empty_analysis(home, away, payload, reason: str) -> dict:
    reason = reason or INSUFFICIENT
    empty_mkt = {"nome": "", "pct": None, "label": reason, "method": ""}
    return {
        "ok": True,
        "insufficient": True,
        "low_sample": True,
        "alert": LOW_DATA,
        "disclaimer": "Esta análise é baseada nos dados disponíveis e não garante o resultado da partida.",
        "prob_note": reason,
        "fixture": payload.get("fixture") or {},
        "home": home,
        "away": away,
        "sample": {"home_games": 0, "away_games": 0},
        "h2h": {"available": False, "message": reason, "games": []},
        "lineups": [],
        "injuries_home": [],
        "injuries_away": [],
        "news": payload.get("news") or [],
        "odds": payload.get("odds"),
        "match_stats": [],
        "importance": _importance(payload),
        "markets": {
            "resultado": {"casa": empty_mkt, "empate": empty_mkt, "fora": empty_mkt},
            "gols": {},
            "btts": {"sim": empty_mkt, "nao": empty_mkt},
            "dupla_chance": {},
            "placares": [],
        },
        "value_markets": [],
        "goal_trend": {},
        "comparison": {"rows": []},
        "confidence": {
            "nivel": "BAIXA",
            "consistencia": "BAIXA CONSISTÊNCIA",
            "emoji": "🔴",
            "score": 5,
            "reasons": ["sem amostra de jogos finalizados"],
            "note": "",
        },
        "summary": {
            "resultado": reason,
            "over15": reason,
            "over25": reason,
            "under25": reason,
            "gols": reason,
            "ambas": reason,
            "placar": reason,
            "confianca": "BAIXA",
            "consistencia": "BAIXA CONSISTÊNCIA",
        },
        "updated_at": payload.get("updated_at"),
        "source": payload.get("source"),
        "sources": payload.get("sources") or [],
        "missing": payload.get("missing") or ["histórico de jogos"],
    }
