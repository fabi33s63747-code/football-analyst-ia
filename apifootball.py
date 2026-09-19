"""Integração opcional com API-Football (api-sports.io). Só é usada se API_FOOTBALL_KEY existir."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any


class ApiFootball:
    def __init__(self):
        self.key = (os.environ.get("API_FOOTBALL_KEY") or "").strip()
        self.base = (os.environ.get("API_FOOTBALL_BASE") or "https://v3.football.api-sports.io").rstrip("/")
        self.header_name = os.environ.get("API_FOOTBALL_HEADER") or "x-apisports-key"

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def get(self, path: str, params: dict | None = None) -> Any:
        if not self.enabled:
            return None
        q = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")})
        url = f"{self.base}{path}"
        if q:
            url += f"?{q}"
        headers = {
            self.header_name: self.key,
            "x-rapidapi-key": self.key,
            "Accept": "application/json",
        }
        if "rapidapi.com" in self.base:
            headers["x-rapidapi-host"] = urllib.parse.urlparse(self.base).netloc
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=18) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def search_team(self, name: str) -> dict | None:
        data = self.get("/teams", {"search": name})
        rows = (data or {}).get("response") or []
        if not rows:
            return None
        t = rows[0].get("team") or {}
        return {"id": t.get("id"), "name": t.get("name"), "logo": t.get("logo")}

    def injuries(self, team_id: int | str, season: int | None = None) -> list[dict]:
        params = {"team": team_id}
        if season:
            params["season"] = season
        data = self.get("/injuries", params)
        out = []
        for row in (data or {}).get("response") or []:
            player = row.get("player") or {}
            fx = row.get("fixture") or {}
            out.append(
                {
                    "player": player.get("name") or "",
                    "status": player.get("type") or row.get("type") or "",
                    "detail": player.get("reason") or "",
                    "fixture": (fx.get("date") or "")[:10],
                }
            )
        return [x for x in out if x["player"]][:12]

    def last_fixtures(self, team_id: int | str, last: int = 10) -> list[dict]:
        data = self.get("/fixtures", {"team": team_id, "last": last})
        games = []
        for row in (data or {}).get("response") or []:
            teams = row.get("teams") or {}
            goals = row.get("goals") or {}
            fx = row.get("fixture") or {}
            league = row.get("league") or {}
            if goals.get("home") is None or goals.get("away") is None:
                continue
            games.append(
                {
                    "id": str(fx.get("id") or ""),
                    "date": (fx.get("date") or "")[:10],
                    "home_id": str((teams.get("home") or {}).get("id") or ""),
                    "away_id": str((teams.get("away") or {}).get("id") or ""),
                    "home": {"id": str((teams.get("home") or {}).get("id") or ""), "name": (teams.get("home") or {}).get("name")},
                    "away": {"id": str((teams.get("away") or {}).get("id") or ""), "name": (teams.get("away") or {}).get("name")},
                    "home_score": int(goals["home"]),
                    "away_score": int(goals["away"]),
                    "competition": league.get("name") or "",
                    "completed": True,
                }
            )
        return games
