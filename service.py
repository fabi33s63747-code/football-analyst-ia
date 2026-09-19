"""Orquestra busca de dados reais + análise. Não preenche lacunas com números inventados."""

from __future__ import annotations

import datetime as dt
from typing import Any

from analysis import analyze_match, compact_row
from apifootball import ApiFootball
from espn_client import (
    LEAGUES,
    EspnClient,
    parse_boxscore_xg_proxy,
    parse_event,
    parse_injuries,
    parse_last_five,
    parse_news,
    parse_odds,
    parse_record,
    parse_rosters,
    parse_schedule_events,
    parse_scoreboard,
    resolve_league,
)

espn = EspnClient(ttl=180)
apif = ApiFootball()


def list_leagues() -> list[dict]:
    return [{"slug": k, **v} for k, v in LEAGUES.items()]


def search_teams(q: str) -> list[dict]:
    if not q or len(q.strip()) < 2:
        return []
    t = espn.search_team(q)
    return [t] if t else []


def fixtures_by_date(date: str | None, league: str | None = None) -> dict:
    ymd = _ymd(date)
    slugs = [resolve_league(league) or league] if league else list(LEAGUES.keys())[:10]
    slugs = [s for s in slugs if s in LEAGUES]
    games = []
    errors = []
    for slug in slugs:
        try:
            raw = espn.scoreboard(slug, ymd)
            for g in parse_scoreboard(raw):
                g["league"] = slug
                g["league_name"] = g.get("league_name") or LEAGUES.get(slug, {}).get("nome")
                g["source"] = "espn"
                games.append(g)
        except Exception as exc:
            errors.append({"league": slug, "error": str(exc)})

    sources = ["espn"]
    try:
        from fotmob_client import matches_by_date as fotmob_day

        extra = fotmob_day(_iso_from_ymd(ymd))
        seen = {
            (
                (g.get("home") or {}).get("name", "").lower(),
                (g.get("away") or {}).get("name", "").lower(),
            )
            for g in games
        }
        added = 0
        if league and games:
            extra = []
        for g in extra:
            name = g.get("league_name") or ""
            if "U18" in name or "U21" in name or "Youth" in name:
                continue
            if not g.get("priority"):
                continue
            key = (g["home"]["name"].lower(), g["away"]["name"].lower())
            if key in seen:
                continue
            seen.add(key)
            games.append(g)
            added += 1
            if added >= 40:
                break
        if added:
            sources.append("fotmob")
    except Exception as exc:
        errors.append({"league": "fotmob", "error": str(exc)})

    games.sort(key=lambda g: g.get("datetime") or "")
    return {
        "date": _iso_from_ymd(ymd),
        "count": len(games),
        "games": games,
        "errors": errors,
        "source": "+".join(sources),
        "updated_at": _now(),
    }


def analyze_query(body: dict, force_refresh: bool = False) -> dict:
    if force_refresh:
        espn.clear_cache()
    home_name = (body.get("home") or body.get("mandante") or "").strip()
    away_name = (body.get("away") or body.get("visitante") or "").strip()
    league_in = (body.get("league") or body.get("campeonato") or "").strip()
    date = (body.get("date") or body.get("data") or "").strip() or None
    event_id = str(body.get("event_id") or body.get("id") or "").strip()
    league_slug = resolve_league(league_in) or (body.get("league_slug") or "").strip()

    missing = []
    fixture = None
    if event_id and league_slug:
        fixture = _fixture_from_event(league_slug, event_id)
    if not fixture:
        if not home_name or not away_name:
            return {"ok": False, "error": "Informe o time mandante e o time visitante."}
        fixture = _resolve_fixture(home_name, away_name, league_slug, date)

    if not fixture:
        return {
            "ok": False,
            "error": "Partida não localizada com os dados informados.",
            "hint": "Confira a grafia dos times ou escolha um jogo da lista do dia.",
        }

    home_id = fixture["home"]["id"]
    away_id = fixture["away"]["id"]
    league = fixture.get("league") or league_slug or fixture.get("home_league") or "eng.1"

    home_team = _load_team(league, home_id, fixture["home"]["name"])
    away_team = _load_team(league, away_id, fixture["away"]["name"])

    home_games = _collect_games(league, home_id, home_team)
    away_games = _collect_games(league, away_id, away_team)
    h2h = _h2h(home_games, away_games, home_id, away_id)

    summary = {}
    if fixture.get("id"):
        try:
            summary = espn.summary(league, fixture["id"])
        except Exception:
            summary = {}

    last5 = parse_last_five(summary) if summary else {}
    if last5.get(home_id):
        home_games = _merge_games(last5[home_id], home_games, home_id)
    if last5.get(away_id):
        away_games = _merge_games(last5[away_id], away_games, away_id)

    current_id = str(fixture.get("id") or "")
    current_date = fixture.get("date")

    def _not_current(g: dict) -> bool:
        if current_id and str(g.get("id") or "") == current_id:
            return False
        pair = {str(g.get("home_id") or ""), str(g.get("away_id") or "")}
        if current_date and pair == {home_id, away_id} and g.get("date") == current_date:
            return False
        return True

    home_games = [g for g in home_games if _not_current(g)]
    away_games = [g for g in away_games if _not_current(g)]

    lineups = parse_rosters(summary) if summary else []
    odds = parse_odds(summary) if summary else None
    match_stats = parse_boxscore_xg_proxy(summary) if summary else []
    news = parse_news(summary.get("news") or {}) if summary else []
    if not news:
        try:
            news = parse_news(espn.news_league(league))
        except Exception:
            news = []

    inj_h = parse_injuries(_safe(lambda: espn.team_injuries(league, home_id)))
    inj_a = parse_injuries(_safe(lambda: espn.team_injuries(league, away_id)))

    source = "espn"
    if apif.enabled:
        source = "espn+api-football"
        # IDs ESPN ≠ IDs API-Football. Busca por nome.
        try:
            th = apif.search_team(home_team.get("name") or fixture["home"]["name"])
            ta = apif.search_team(away_team.get("name") or fixture["away"]["name"])
            year = dt.datetime.utcnow().year
            if th and th.get("id"):
                extra = apif.injuries(th["id"], year) or apif.injuries(th["id"], year - 1)
                if extra:
                    inj_h = extra
                extra_g = apif.last_fixtures(th["id"], 10)
                if extra_g:
                    home_games = _merge_games(extra_g, home_games, str(th["id"]))
            if ta and ta.get("id"):
                extra = apif.injuries(ta["id"], year) or apif.injuries(ta["id"], year - 1)
                if extra:
                    inj_a = extra
                extra_g = apif.last_fixtures(ta["id"], 10)
                if extra_g:
                    away_games = _merge_games(extra_g, away_games, str(ta["id"]))
        except Exception as exc:
            missing.append(f"api-football: {exc}")

    if not lineups:
        missing.append("escalação oficial ainda não publicada")
    if not inj_h and not inj_a:
        missing.append("desfalques")
    if not any(s.get("xg") for s in match_stats):
        missing.append("xG")
    if len(home_games) < 10:
        missing.append("últimos 10 jogos do mandante incompletos")
    if len(away_games) < 10:
        missing.append("últimos 10 jogos do visitante incompletos")

    payload = {
        "fixture": {
            "id": fixture.get("id"),
            "date": fixture.get("date"),
            "status": fixture.get("status"),
            "league": league,
            "league_name": fixture.get("league_name") or LEAGUES.get(league, {}).get("nome") or league,
            "venue": fixture.get("venue"),
            "home_name": fixture["home"]["name"],
            "away_name": fixture["away"]["name"],
            "home_logo": fixture["home"].get("logo") or home_team.get("logo"),
            "away_logo": fixture["away"].get("logo") or away_team.get("logo"),
            "label": f"{fixture['home']['name']} x {fixture['away']['name']}",
            "completed": fixture.get("completed"),
            "score": None
            if not fixture.get("completed")
            else f"{fixture.get('home_score')}-{fixture.get('away_score')}",
        },
        "home": {
            "id": home_id,
            "name": home_team.get("name") or fixture["home"]["name"],
            "logo": home_team.get("logo") or fixture["home"].get("logo"),
            "record": home_team,
        },
        "away": {
            "id": away_id,
            "name": away_team.get("name") or fixture["away"]["name"],
            "logo": away_team.get("logo") or fixture["away"].get("logo"),
            "record": away_team,
        },
        "home_games": home_games,
        "away_games": away_games,
        "h2h": h2h,
        "lineups": lineups,
        "injuries_home": inj_h,
        "injuries_away": inj_a,
        "news": news[:6],
        "odds": odds,
        "match_stats": match_stats,
        "updated_at": _now(),
        "source": source,
        "sources": [
            {
                "name": "ESPN public JSON",
                "use": "jogos, forma, tabela, escalação, odds e notícias quando publicadas",
                "current": True,
            },
            {
                "name": "API-Football",
                "use": "desfalques e histórico extra",
                "current": bool(apif.enabled),
            },
        ],
        "missing": missing,
        "importance": _importance_text(home_team, away_team, fixture),
    }
    result = analyze_match(payload)
    result["ok"] = True
    return result


def analyze_many(items: list[dict], force_refresh: bool = False) -> dict:
    rows = []
    details = []
    for item in items:
        try:
            analysis = analyze_query(item, force_refresh=force_refresh)
        except Exception as exc:
            analysis = {
                "ok": False,
                "insufficient": True,
                "fixture": {
                    "label": f"{item.get('home','')} x {item.get('away','')}",
                    "home_name": item.get("home"),
                    "away_name": item.get("away"),
                },
                "error": str(exc),
            }
        rows.append(compact_row(analysis) if analysis.get("ok") else compact_row(analysis))
        details.append(analysis)
        force_refresh = False
    return {"ok": True, "count": len(rows), "rows": rows, "details": details, "updated_at": _now()}


def _resolve_fixture(home_name: str, away_name: str, league_slug: str | None, date: str | None) -> dict | None:
    home = espn.search_team(home_name)
    away = espn.search_team(away_name)
    if not home or not away:
        return None
    league = league_slug or home.get("league") or away.get("league") or "eng.1"
    ymd = _ymd(date) if date else None

    # 1) placar do dia nas ligas dos dois times
    slugs = []
    for s in (league, home.get("league"), away.get("league")):
        if s and s not in slugs:
            slugs.append(s)
    for slug in slugs:
        try:
            raw = espn.scoreboard(slug, ymd)
        except Exception:
            continue
        for g in parse_scoreboard(raw):
            if _same_pair(g, home["id"], away["id"]):
                g["league"] = slug
                g["league_name"] = g.get("league_name") or LEAGUES.get(slug, {}).get("nome")
                return g

    # 2) próximos jogos do mandante
    try:
        sched = espn.team_schedule(league, home["id"])
        for ev in parse_schedule_events(sched, home["id"]):
            if _same_pair(ev, home["id"], away["id"]):
                ev["league"] = league
                ev["league_name"] = LEAGUES.get(league, {}).get("nome")
                ev["home"]["logo"] = ev["home"].get("logo") or home.get("logo")
                ev["away"]["logo"] = ev["away"].get("logo") or away.get("logo")
                return ev
    except Exception:
        pass

    # 3) partida virtual (ainda não listada) — análise com histórico, sem inventar o jogo
    return {
        "id": "",
        "date": _iso_from_ymd(ymd) if ymd else None,
        "status": "Programada / não confirmada na fonte",
        "completed": False,
        "league": league,
        "league_name": LEAGUES.get(league, {}).get("nome") or league,
        "venue": "",
        "home": {"id": home["id"], "name": home["name"], "logo": home.get("logo"), "abbreviation": home.get("abbreviation")},
        "away": {"id": away["id"], "name": away["name"], "logo": away.get("logo"), "abbreviation": away.get("abbreviation")},
        "home_score": None,
        "away_score": None,
    }


def _fixture_from_event(league: str, event_id: str) -> dict | None:
    try:
        summary = espn.summary(league, event_id)
    except Exception:
        return None
    header = summary.get("header") or {}
    comps = header.get("competitions") or [{}]
    ev = {
        "id": header.get("id") or event_id,
        "date": (comps[0].get("date") if comps else "") or "",
        "name": "",
        "status": ((comps[0].get("status") or {}).get("type") if comps else {}) or {},
        "competitions": comps,
    }
    parsed = parse_event(ev)
    if not parsed:
        return None
    parsed["league"] = league
    parsed["league_name"] = (header.get("league") or {}).get("name") or LEAGUES.get(league, {}).get("nome")
    return parsed


def _load_team(league: str, team_id: str, fallback_name: str) -> dict:
    try:
        raw = espn.team_detail(league, team_id)
        rec = parse_record(raw)
        if rec.get("name"):
            return rec
    except Exception:
        pass
    return {"id": team_id, "name": fallback_name, "logo": f"https://a.espncdn.com/i/teamlogos/soccer/500/{team_id}.png"}


def _collect_games(league: str, team_id: str, team: dict) -> list[dict]:
    games = []
    year = dt.datetime.utcnow().year
    for season in (None, year, year - 1):
        try:
            raw = espn.team_schedule(league, team_id, season)
            games.extend(parse_schedule_events(raw, team_id))
        except Exception:
            continue
        finished = [g for g in games if g.get("completed") and g.get("home_score") is not None]
        if len(finished) >= 10:
            break
    # normalizar ids
    for g in games:
        g["home_id"] = str((g.get("home") or {}).get("id") or g.get("home_id") or "")
        g["away_id"] = str((g.get("away") or {}).get("id") or g.get("away_id") or "")
        g["home_name"] = (g.get("home") or {}).get("name")
        g["away_name"] = (g.get("away") or {}).get("name")
    finished = [g for g in games if g.get("home_score") is not None]
    # unique by id+date
    seen = set()
    out = []
    for g in sorted(finished, key=lambda x: x.get("date") or "", reverse=True):
        key = (g.get("id"), g.get("date"), g.get("home_score"), g.get("away_score"))
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out[:12]


def _merge_games(extra: list[dict], base: list[dict], team_id: str) -> list[dict]:
    mapped = []
    for g in extra:
        row = dict(g)
        if "home_id" not in row:
            continue
        if row.get("home_score") is None:
            continue
        mapped.append(row)
    return _dedupe(mapped + base)[:12]


def _dedupe(games: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for g in sorted(games, key=lambda x: x.get("date") or "", reverse=True):
        key = (g.get("date"), g.get("home_score"), g.get("away_score"), g.get("home_id"), g.get("away_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out


def _h2h(home_games: list[dict], away_games: list[dict], home_id: str, away_id: str) -> list[dict]:
    ids = {away_id}
    out = []
    for g in home_games + away_games:
        hid, aid = str(g.get("home_id")), str(g.get("away_id"))
        pair = {hid, aid}
        if home_id in pair and away_id in pair and g.get("home_score") is not None:
            out.append(g)
    return _dedupe(out)[:8]


def _same_pair(g: dict, id_a: str, id_b: str) -> bool:
    ids = {str((g.get("home") or {}).get("id") or g.get("home_id")), str((g.get("away") or {}).get("id") or g.get("away_id"))}
    return {str(id_a), str(id_b)} == ids


def _importance_text(home: dict, away: dict, fixture: dict) -> str:
    bits = []
    league = fixture.get("league_name") or ""
    if league:
        bits.append(f"Competição: {league}.")
    if home.get("standing"):
        bits.append(f"Mandante: {home['standing']}.")
    if away.get("standing"):
        bits.append(f"Visitante: {away['standing']}.")
    if home.get("record") and away.get("record"):
        bits.append(f"Campanha no campeonato: {home.get('name','Casa')} {home['record']} × {away.get('name','Fora')} {away['record']}.")
    if not bits:
        return "Dados de tabela insuficientes para classificar a importância."
    bits.append("A importância é contextual e não altera sozinha as frequências observadas.")
    return " ".join(bits)


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _ymd(date: str | None) -> str:
    if not date:
        return dt.datetime.utcnow().strftime("%Y%m%d")
    digits = "".join(c for c in date if c.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return dt.datetime.utcnow().strftime("%Y%m%d")


def _iso_from_ymd(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def _now() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
