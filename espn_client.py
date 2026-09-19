"""Cliente ESPN (JSON público, sem chave). Nunca inventa placar ou estatística."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (compatible; FootballAnalystIA/1.0; +https://localhost) "
    "AppleWebKit/537.36"
)
SITE = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"
WEB = "https://site.web.api.espn.com/apis/common/v3/search"
STANDINGS = "https://site.web.api.espn.com/apis/v2/sports/soccer"
SITE_FALLBACK = "https://site.api.espn.com/apis/site/v2/sports/soccer"

LEAGUES: dict[str, dict[str, str]] = {
    "eng.1": {"nome": "Premier League", "pais": "Inglaterra"},
    "esp.1": {"nome": "La Liga", "pais": "Espanha"},
    "ita.1": {"nome": "Serie A", "pais": "Itália"},
    "ger.1": {"nome": "Bundesliga", "pais": "Alemanha"},
    "fra.1": {"nome": "Ligue 1", "pais": "França"},
    "por.1": {"nome": "Primeira Liga", "pais": "Portugal"},
    "ned.1": {"nome": "Eredivisie", "pais": "Países Baixos"},
    "bra.1": {"nome": "Brasileirão Série A", "pais": "Brasil"},
    "arg.1": {"nome": "Liga Profesional", "pais": "Argentina"},
    "usa.1": {"nome": "MLS", "pais": "EUA"},
    "mex.1": {"nome": "Liga MX", "pais": "México"},
    "tur.1": {"nome": "Süper Lig", "pais": "Turquia"},
    "bel.1": {"nome": "Pro League", "pais": "Bélgica"},
    "sco.1": {"nome": "Scottish Premiership", "pais": "Escócia"},
    "uefa.champions": {"nome": "UEFA Champions League", "pais": "Europa"},
    "uefa.europa": {"nome": "UEFA Europa League", "pais": "Europa"},
    "uefa.europa.conf": {"nome": "UEFA Conference League", "pais": "Europa"},
    "conmebol.libertadores": {"nome": "Copa Libertadores", "pais": "América do Sul"},
    "conmebol.sudamericana": {"nome": "Copa Sudamericana", "pais": "América do Sul"},
    "fifa.world": {"nome": "Copa do Mundo", "pais": "FIFA"},
}

LEAGUE_ALIASES = {
    "premier": "eng.1",
    "premier league": "eng.1",
    "epl": "eng.1",
    "inglaterra": "eng.1",
    "la liga": "esp.1",
    "laliga": "esp.1",
    "espanha": "esp.1",
    "serie a": "ita.1",
    "série a": "ita.1",
    "italia": "ita.1",
    "itália": "ita.1",
    "bundesliga": "ger.1",
    "alemanha": "ger.1",
    "ligue 1": "fra.1",
    "franca": "fra.1",
    "frança": "fra.1",
    "brasileirao": "bra.1",
    "brasileirão": "bra.1",
    "serie a brasil": "bra.1",
    "champions": "uefa.champions",
    "champions league": "uefa.champions",
    "liga dos campeoes": "uefa.champions",
    "liga dos campeões": "uefa.champions",
    "europa league": "uefa.europa",
    "libertadores": "conmebol.libertadores",
    "primeira liga": "por.1",
    "portugal": "por.1",
}


class EspnClient:
    def __init__(self, ttl: int = 180):
        self.ttl = ttl
        self._cache: dict[str, tuple[float, Any]] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    def get(self, url: str, timeout: int = 18) -> Any:
        now = time.time()
        hit = self._cache.get(url)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Referer": "https://www.espn.com/soccer/",
        }
        urls = [url]
        if SITE in url:
            urls.append(url.replace(SITE, SITE_FALLBACK))
        last_err = None
        for candidate in urls:
            try:
                req = urllib.request.Request(candidate, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                self._cache[url] = (now, data)
                return data
            except Exception as exc:
                last_err = exc
                continue
        raise last_err or RuntimeError("falha ao consultar ESPN")

    def search_team(self, name: str) -> dict | None:
        q = urllib.parse.quote(name.strip())
        url = f"{WEB}?query={q}&limit=20&type=team"
        try:
            data = self.get(url)
        except Exception:
            return None
        items = data.get("items") or []
        soccer = [i for i in items if (i.get("sport") or "").lower() == "soccer"]
        pool = soccer or items
        if not pool:
            return None
        needle = _norm(name)
        exact = next((i for i in pool if _norm(i.get("displayName") or "") == needle), None)
        item = exact or pool[0]
        league = item.get("defaultLeagueSlug") or item.get("league") or ""
        return {
            "id": str(item.get("id") or ""),
            "name": item.get("displayName") or name,
            "abbreviation": item.get("abbreviation") or "",
            "league": league,
            "logo": _logo(item),
            "color": item.get("color") or "1f8a4c",
        }

    def team_detail(self, league: str, team_id: str) -> dict:
        return self.get(f"{SITE}/{league}/teams/{team_id}") or {}

    def team_schedule(self, league: str, team_id: str, season: int | None = None) -> dict:
        url = f"{SITE}/{league}/teams/{team_id}/schedule"
        if season:
            url += f"?season={season}"
        return self.get(url) or {}

    def team_injuries(self, league: str, team_id: str) -> Any:
        try:
            return self.get(f"{SITE}/{league}/teams/{team_id}/injuries")
        except Exception:
            return None

    def team_news(self, league: str, team_id: str) -> Any:
        try:
            return self.get(f"{SITE}/{league}/teams/{team_id}/news")
        except Exception:
            return None

    def scoreboard(self, league: str, date_yyyymmdd: str | None = None) -> dict:
        url = f"{SITE}/{league}/scoreboard"
        if date_yyyymmdd:
            url += f"?dates={date_yyyymmdd}"
        return self.get(url) or {}

    def summary(self, league: str, event_id: str) -> dict:
        return self.get(f"{SITE}/{league}/summary?event={event_id}") or {}

    def news_league(self, league: str) -> dict:
        try:
            return self.get(f"{SITE}/{league}/news") or {}
        except Exception:
            return {}


def resolve_league(text: str | None) -> str | None:
    if not text:
        return None
    raw = text.strip()
    if raw in LEAGUES:
        return raw
    key = _norm(raw)
    if key in LEAGUE_ALIASES:
        return LEAGUE_ALIASES[key]
    for slug, meta in LEAGUES.items():
        if key == _norm(meta["nome"]) or key in _norm(meta["nome"]):
            return slug
    return None


def _norm(s: str) -> str:
    table = str.maketrans(
        "áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ",
        "aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN",
    )
    return " ".join(s.translate(table).lower().split())


def _logo(item: dict) -> str:
    logos = item.get("logos") or []
    if logos:
        return logos[0].get("href") or ""
    return f"https://a.espncdn.com/i/teamlogos/soccer/500/{item.get('id')}.png"


def parse_record(team_payload: dict) -> dict:
    team = team_payload.get("team") or team_payload
    rec = ((team.get("record") or {}).get("items") or [{}])[0]
    stats = {s.get("name"): s.get("value") for s in rec.get("stats") or []}
    logo = ""
    logos = team.get("logos") or []
    if logos:
        logo = logos[0].get("href") or ""
    return {
        "id": str(team.get("id") or ""),
        "name": team.get("displayName") or team.get("name") or "",
        "abbreviation": team.get("abbreviation") or "",
        "logo": logo,
        "standing": team.get("standingSummary") or "",
        "record": rec.get("summary") or "",
        "games": _num(stats.get("gamesPlayed")),
        "wins": _num(stats.get("wins")),
        "draws": _num(stats.get("ties")),
        "losses": _num(stats.get("losses")),
        "gf": _num(stats.get("pointsFor")),
        "ga": _num(stats.get("pointsAgainst")),
        "home_games": _num(stats.get("homeGamesPlayed")),
        "home_wins": _num(stats.get("homeWins")),
        "home_draws": _num(stats.get("homeTies")),
        "home_losses": _num(stats.get("homeLosses")),
        "home_gf": _num(stats.get("homePointsFor")),
        "home_ga": _num(stats.get("homePointsAgainst")),
        "away_games": _num(stats.get("awayGamesPlayed")),
        "away_wins": _num(stats.get("awayWins")),
        "away_draws": _num(stats.get("awayTies")),
        "away_losses": _num(stats.get("awayLosses")),
        "away_gf": _num(stats.get("awayPointsFor")),
        "away_ga": _num(stats.get("awayPointsAgainst")),
        "points": _num(stats.get("points")),
        "rank": _num(stats.get("rank")),
    }


def parse_schedule_events(payload: dict, team_id: str) -> list[dict]:
    out = []
    for ev in payload.get("events") or []:
        parsed = parse_event(ev, prefer_team=team_id)
        if parsed:
            out.append(parsed)
    return out


def parse_event(ev: dict, prefer_team: str | None = None) -> dict | None:
    comps = ev.get("competitions") or [{}]
    comp = comps[0] if comps else {}
    teams = comp.get("competitors") or []
    home = next((t for t in teams if t.get("homeAway") == "home"), teams[0] if teams else None)
    away = next((t for t in teams if t.get("homeAway") == "away"), teams[1] if len(teams) > 1 else None)
    if not home or not away:
        return None
    status = (ev.get("status") or comp.get("status") or {}).get("type") or {}
    hs = _score(home)
    aws = _score(away)
    state = (status.get("name") or status.get("state") or "").upper()
    completed = bool(status.get("completed")) or state in {
        "STATUS_FINAL",
        "STATUS_FULL_TIME",
        "POST",
    }
    if hs is not None and aws is not None and state not in {"STATUS_SCHEDULED", "STATUS_PRE", "PRE"}:
        # calendário da ESPN às vezes omite o flag completed
        completed = True
    scored = completed and hs is not None and aws is not None
    return {
        "id": str(ev.get("id") or comp.get("id") or ""),
        "date": (ev.get("date") or "")[:10],
        "datetime": ev.get("date") or "",
        "name": ev.get("name") or ev.get("shortName") or "",
        "league": ((ev.get("competitions") or [{}])[0].get("notes") or [None]),
        "status": status.get("description") or status.get("detail") or status.get("name") or "",
        "completed": bool(scored),
        "home": _competitor(home),
        "away": _competitor(away),
        "home_score": hs if scored else None,
        "away_score": aws if scored else None,
        "venue": ((comp.get("venue") or {}).get("fullName") or ""),
    }


def parse_scoreboard(payload: dict) -> list[dict]:
    league_name = ""
    leagues = payload.get("leagues") or []
    if leagues:
        league_name = leagues[0].get("name") or ""
    games = []
    for ev in payload.get("events") or []:
        g = parse_event(ev)
        if not g:
            continue
        g["league_name"] = league_name
        games.append(g)
    return games


def parse_last_five(summary: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for block in summary.get("lastFiveGames") or []:
        team = block.get("team") or {}
        tid = str(team.get("id") or "")
        games = []
        for e in block.get("events") or []:
            hs = _to_int(e.get("homeTeamScore"))
            aws = _to_int(e.get("awayTeamScore"))
            if hs is None or aws is None:
                continue
            opp = (e.get("opponent") or {}).get("displayName") or ""
            at_vs = e.get("atVs") or ""
            team_name = team.get("displayName") or ""
            if at_vs == "@":
                home_name, away_name = opp, team_name
            else:
                home_name, away_name = team_name, opp
            games.append(
                {
                    "id": str(e.get("id") or ""),
                    "date": (e.get("gameDate") or "")[:10],
                    "home_id": str(e.get("homeTeamId") or ""),
                    "away_id": str(e.get("awayTeamId") or ""),
                    "home_score": hs,
                    "away_score": aws,
                    "home_name": home_name,
                    "away_name": away_name,
                    "home": {"id": str(e.get("homeTeamId") or ""), "name": home_name},
                    "away": {"id": str(e.get("awayTeamId") or ""), "name": away_name},
                    "result": e.get("gameResult") or "",
                    "opponent": opp,
                    "competition": e.get("leagueName") or e.get("competitionName") or "",
                    "at_vs": at_vs,
                    "completed": True,
                }
            )
        out[tid] = games
    return out


def parse_rosters(summary: dict) -> list[dict]:
    rows = []
    for side in summary.get("rosters") or []:
        team = side.get("team") or {}
        starters = []
        bench = []
        for p in side.get("roster") or []:
            name = ((p.get("athlete") or {}).get("displayName")) or ""
            pos = ((p.get("position") or {}).get("abbreviation")) or ""
            jersey = p.get("jersey") or ""
            item = {"name": name, "pos": pos, "jersey": jersey}
            if p.get("starter"):
                starters.append(item)
            else:
                bench.append(item)
        rows.append(
            {
                "team": team.get("displayName") or "",
                "team_id": str(team.get("id") or ""),
                "home_away": side.get("homeAway") or "",
                "formation": side.get("formation") or "",
                "starters": starters,
                "bench": bench[:8],
            }
        )
    return rows


def parse_odds(summary: dict) -> dict | None:
    pc = summary.get("pickcenter") or []
    if not pc:
        return None
    row = pc[0]
    home = row.get("homeTeamOdds") or {}
    away = row.get("awayTeamOdds") or {}
    draw = row.get("drawOdds") or {}
    return {
        "provider": (row.get("provider") or {}).get("name") or "",
        "home_ml": home.get("moneyLine"),
        "draw_ml": draw.get("moneyLine"),
        "away_ml": away.get("moneyLine"),
        "over_under": row.get("overUnder"),
        "over_odds": row.get("overOdds"),
        "under_odds": row.get("underOdds"),
        "details": row.get("details") or "",
    }


def parse_news(payload: dict, limit: int = 6) -> list[dict]:
    arts = []
    if isinstance(payload, dict):
        arts = payload.get("articles") or (payload.get("news") or {}).get("articles") or []
    out = []
    for a in arts[:limit]:
        out.append(
            {
                "title": a.get("headline") or a.get("title") or "",
                "description": a.get("description") or "",
                "published": a.get("published") or a.get("lastModified") or "",
                "url": ((a.get("links") or {}).get("web") or {}).get("href")
                or ((a.get("links") or {}).get("api") or {}).get("self")
                or "",
            }
        )
    return [x for x in out if x["title"]]


def parse_injuries(payload: Any) -> list[dict]:
    if not payload:
        return []
    items = []
    if isinstance(payload, dict):
        items = payload.get("injuries") or payload.get("items") or []
        if not items and "athletes" in payload:
            items = payload.get("athletes") or []
    elif isinstance(payload, list):
        items = payload
    out = []
    for it in items:
        athlete = it.get("athlete") or it.get("player") or {}
        out.append(
            {
                "player": athlete.get("displayName") or it.get("displayName") or "",
                "status": (it.get("status") or it.get("type") or {}).get("description")
                if isinstance(it.get("status"), dict)
                else (it.get("status") or it.get("type") or ""),
                "detail": it.get("longComment") or it.get("shortComment") or it.get("reason") or "",
            }
        )
    return [x for x in out if x["player"]]


def parse_boxscore_xg_proxy(summary: dict) -> list[dict]:
    """Estatísticas de finalização/posse quando existirem. xG só se vier no JSON."""
    teams = ((summary.get("boxscore") or {}).get("teams")) or []
    out = []
    for t in teams:
        stats = {s.get("name"): s.get("displayValue") or s.get("value") for s in t.get("statistics") or []}
        team = t.get("team") or {}
        xg = stats.get("expectedGoals") or stats.get("xg") or stats.get("expected_goals")
        out.append(
            {
                "team": team.get("displayName") or "",
                "team_id": str(team.get("id") or ""),
                "possession": stats.get("possessionPct"),
                "shots": stats.get("totalShots"),
                "shots_on_target": stats.get("shotsOnTarget"),
                "xg": xg,
                "corners": stats.get("wonCorners"),
                "fouls": stats.get("foulsCommitted"),
            }
        )
    return out


def _competitor(t: dict) -> dict:
    team = t.get("team") or {}
    logos = team.get("logos") or []
    return {
        "id": str(team.get("id") or t.get("id") or ""),
        "name": team.get("displayName") or team.get("name") or "",
        "abbreviation": team.get("abbreviation") or "",
        "logo": logos[0].get("href") if logos else "",
        "winner": bool(t.get("winner")),
    }


def _score(t: dict) -> int | None:
    raw = t.get("score")
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = raw.get("displayValue") or raw.get("value")
    return _to_int(raw)


def _to_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
