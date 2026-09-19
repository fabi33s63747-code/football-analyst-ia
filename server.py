#!/usr/bin/env python3
"""Servidor local do FOOTBALL ANALYST IA (biblioteca padrão)."""

from __future__ import annotations

import json
import os
import posixpath
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

# carrega .env simples
env_path = os.path.join(ROOT, ".env")
if os.path.isfile(env_path):
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from service import analyze_many, analyze_query, fixtures_by_date, list_leagues, search_teams  # noqa: E402

HISTORY_PATH = os.path.join(ROOT, "data", "history.json")


def _load_history():
    if not os.path.isfile(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return []


def _save_history_item(analysis: dict) -> None:
    if not analysis or not analysis.get("ok"):
        return
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    fx = analysis.get("fixture") or {}
    sm = analysis.get("summary") or {}
    conf = analysis.get("confidence") or {}
    item = {
        "id": fx.get("id") or f"{fx.get('home_name')}-{fx.get('away_name')}-{fx.get('date')}",
        "label": fx.get("label"),
        "date": fx.get("date"),
        "league": fx.get("league_name"),
        "updated_at": analysis.get("updated_at"),
        "summary": sm,
        "consistencia": conf.get("consistencia") or sm.get("consistencia"),
        "source": analysis.get("source"),
    }
    rows = [r for r in _load_history() if r.get("id") != item["id"]]
    rows.insert(0, item)
    with open(HISTORY_PATH, "w", encoding="utf-8") as fh:
        json.dump(rows[:40], fh, ensure_ascii=False, indent=2)


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/api/health":
            return self._json(
                {
                    "ok": True,
                    "app": "FOOTBALL ANALYST IA",
                    "provider": "espn",
                    "api_football": bool(os.environ.get("API_FOOTBALL_KEY")),
                }
            )
        if path == "/api/leagues":
            return self._json({"ok": True, "leagues": list_leagues()})
        if path == "/api/search":
            q = (qs.get("q") or [""])[0]
            return self._json({"ok": True, "teams": search_teams(q)})
        if path == "/api/fixtures":
            date = (qs.get("date") or [None])[0]
            league = (qs.get("league") or [None])[0]
            try:
                return self._json({"ok": True, **fixtures_by_date(date, league)})
            except Exception as exc:
                return self._json({"ok": False, "error": str(exc)}, 502)
        if path == "/api/history":
            return self._json({"ok": True, "items": _load_history()})
        if path in ("/", "/index.html"):
            return self._file("templates/index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            return self._file(path.lstrip("/"))
        return self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return self._json({"ok": False, "error": "JSON inválido"}, 400)

        refresh = bool(body.get("refresh") or self.headers.get("X-Refresh") == "1")
        try:
            if path == "/api/analyze":
                result = analyze_query(body, force_refresh=refresh)
                if result.get("ok"):
                    _save_history_item(result)
                return self._json(result, 200 if result.get("ok") else 400)
            if path == "/api/analyze-many":
                items = body.get("games") or body.get("jogos") or []
                if not items:
                    return self._json({"ok": False, "error": "Envie a lista de jogos."}, 400)
                return self._json(analyze_many(items, force_refresh=refresh))
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)}, 500)
        return self._json({"ok": False, "error": "not found"}, 404)

    def _json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _file(self, rel, content_type=None):
        rel = posixpath.normpath(rel).lstrip("/")
        full = os.path.join(ROOT, rel)
        if not os.path.isfile(full):
            return self._json({"ok": False, "error": "arquivo não encontrado"}, 404)
        if content_type is None:
            if rel.endswith(".css"):
                content_type = "text/css; charset=utf-8"
            elif rel.endswith(".js"):
                content_type = "application/javascript; charset=utf-8"
            elif rel.endswith(".svg"):
                content_type = "image/svg+xml"
            else:
                content_type = "application/octet-stream"
        with open(full, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,X-Refresh")

    def guess_type(self, path):
        return super().guess_type(path)


def main():
    port = int(os.environ.get("PORT") or 8080)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"FOOTBALL ANALYST IA  →  http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrado")


if __name__ == "__main__":
    main()
