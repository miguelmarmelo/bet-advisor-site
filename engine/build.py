"""Motor do painel Bet Advisor.

Corre 3 vezes por semana (GitHub Actions). Em cada execução:
  1. Vai buscar as odds dos jogos dos próximos 7 dias:
       - OddsPapi: Pinnacle (hipótese real) e betano.pt (casa portuguesa), todos os mercados
       - The Odds API: resultado final (1X2) em várias casas internacionais
  2. Calcula para cada aposta a hipótese real, a odd mínima, o ganho esperado e a classificação.
  3. Regista no "Daqui para a frente" as apostas que a app assinala, com a odd e a hora.
  4. Junta os resultados dos jogos já disputados (football-data.co.uk e The Odds API) e liquida o registo.
  5. Escreve docs/data/panel.json e docs/data/tracker.json, que o site lê.

Só usa a biblioteca padrão do Python.
"""
import csv, difflib, io, json, math, os, re, sys, time, unicodedata, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ENG = ROOT / "engine"
OUT = ROOT / "docs" / "data"
DATA = ROOT / "data"
LIS = ZoneInfo("Europe/Lisbon")
NOW = datetime.now(timezone.utc)
TODAY = NOW.astimezone(LIS).date()

ODDSPAPI_KEY = os.environ.get("ODDSPAPI_KEY", "")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDSPAPI_CAP = int(os.environ.get("ODDSPAPI_CAP", "244"))   # de 250 por mês
ODDS_API_RESERVE = int(os.environ.get("ODDS_API_RESERVE", "20"))

COMPS = [  # (OddsPapi id, nome, chave The Odds API, código football-data)
    (17, "Premier League", "soccer_epl", "E0"),
    (8, "La Liga", "soccer_spain_la_liga", "SP1"),
    (35, "Bundesliga", "soccer_germany_bundesliga", "D1"),
    (23, "Serie A", "soccer_italy_serie_a", "I1"),
    (34, "Ligue 1", "soccer_france_ligue_one", "F1"),
    (238, "Liga Portugal", "soccer_portugal_primeira_liga", "P1"),
    (7, "Liga dos Campeões", "soccer_uefa_champs_league", None),
    (679, "Liga Europa", "soccer_uefa_europa_league", None),
    (34480, "Conference", "soccer_uefa_europa_conference_league", None),
]
TNAME = {c[0]: c[1] for c in COMPS}
CATS = ["1X2", "Golos 2,5", "Outras linhas de golos", "Ambas marcam", "Dupla hipótese",
        "Empate anula aposta", "Cantos", "1.ª parte"]
TESTED = {"1X2"}                                   # só o 1X2 passou o teste com jogos passados
DIAS = ["seg.", "ter.", "qua.", "qui.", "sex.", "sáb.", "dom."]
MESES = ["jan.", "fev.", "mar.", "abr.", "mai.", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez."]
EXCH = {"matchbook", "betfair_ex_eu", "betfair_ex_uk", "pinnacle"}
log_lines = []


def log(msg):
    print(msg, flush=True); log_lines.append(msg)


# ---------------------------------------------------------------- utilidades
def http_json(url, timeout=120):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read()), r.headers
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404, 422):
                return None, None
            time.sleep(5 * (attempt + 1))
        except urllib.error.URLError:
            time.sleep(5 * (attempt + 1))
    return None, None


def http_text(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bet-advisor"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return None


def power_devig(odds):
    """Remove a comissão da casa pelo método de potência: devolve probabilidades que somam 1."""
    inv = [1 / o for o in odds]
    lo, hi = 0.3, 4.0
    f = lambda k: sum(x ** k for x in inv) - 1
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0: hi = mid
        else: lo = mid
    k = (lo + hi) / 2
    return [x ** k for x in inv]


def fnum(x, n=2):
    return f"{x:.{n}f}".replace(".", ",")


def local(dt_iso):
    t = datetime.fromisoformat(dt_iso.replace("Z", "+00:00")).astimezone(LIS)
    return t, f"{DIAS[t.weekday()]} {t.day} {MESES[t.month - 1]}, {t:%Hh%M}"


def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    stop = {"fc", "cf", "sc", "ac", "as", "ssc", "afc", "sl", "cp", "bc", "club", "de", "calcio", "fk", "sk",
            "sv", "vfb", "vfl", "tsg", "fsv", "rc", "ogc", "1", "07", "04", "05", "1899", "1999", "the", "cd", "ud", "rcd", "sd", "ca", "bk"}
    return " ".join(t for t in s.split() if t not in stop)


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    jac = len(ta & tb) / len(ta | tb)
    sub = 1.0 if (a in b or b in a) else 0.0
    return max(jac, difflib.SequenceMatcher(None, a, b).ratio(), 0.9 * sub)


# ---------------------------------------------------------------- OddsPapi
def oddspapi_used():
    d, _ = http_json(f"https://api.oddspapi.io/v4/account?apiKey={ODDSPAPI_KEY}", 30)
    if not d:
        return None
    return int(d["subscriptions"][0]["request_count"])


def fetch_oddspapi():
    if not ODDSPAPI_KEY:
        log("OddsPapi: sem chave"); return None
    used = oddspapi_used()
    groups = ["17,8,35", "23,34,238", "7,679,34480"]
    need = 2 * len(groups)
    if used is None or used + need > ODDSPAPI_CAP:
        log(f"OddsPapi: saltado (pedidos usados este mês: {used})"); return None
    out = {}
    for bk in ("pinnacle", "betano.pt"):
        fx = {}
        for g in groups:
            d, _ = http_json(f"https://api.oddspapi.io/v4/odds-by-tournaments?tournamentIds={g}&bookmaker={bk}&apiKey={ODDSPAPI_KEY}")
            for x in (d or []):
                fx[x["fixtureId"]] = x
            time.sleep(2)
        out[bk] = fx
    log(f"OddsPapi: {len(out['pinnacle'])} jogos Pinnacle, {len(out['betano.pt'])} jogos betano.pt (pedidos no mês: {used + need})")
    return out


def participant_names(ids):
    pf = ENG / "participants.json"
    names = json.loads(pf.read_text())
    missing = [i for i in ids if str(i) not in names]
    if missing and ODDSPAPI_KEY:
        used = oddspapi_used()
        if used is not None and used + 1 <= ODDSPAPI_CAP:
            d, _ = http_json(f"https://api.oddspapi.io/v4/participants?sportId=10&apiKey={ODDSPAPI_KEY}")
            if d:
                names.update(d); pf.write_text(json.dumps(names, ensure_ascii=False, separators=(",", ":")))
                log(f"Nomes de equipas atualizados ({len(missing)} em falta)")
    return names


# ---------------------------------------------------------------- opções betano.pt vs Pinnacle
def price(o):
    p = (o or {}).get("players", {}).get("0")
    if isinstance(p, list):
        p = p[-1] if p else None
    return p["price"] if p and p.get("price", 0) > 1 else None


def build_pt(op, limit_date):
    M = json.loads((ENG / "markets.json").read_text())
    P, B = op["pinnacle"], op["betano.pt"]
    common = [f for f in P if f in B]
    names = participant_names({P[f]["participant1Id"] for f in common} | {P[f]["participant2Id"] for f in common})
    opts, counts, games = [], {}, {}
    for fid in common:
        x = P[fid]
        t, quando = local(x["startTime"])
        if t.date() > limit_date or t < NOW.astimezone(LIS):
            continue
        home = names.get(str(x["participant1Id"]), "?"); away = names.get(str(x["participant2Id"]), "?")
        d = t.date().isoformat()
        base = dict(fid=fid, jogo=f"{home} – {away}", home=home, away=away, comp=TNAME.get(x["tournamentId"], "?"),
                    date=d, quando=quando, kickoff=x["startTime"])
        games.setdefault(d, set()).add(fid)
        pm = x["bookmakerOdds"]["pinnacle"]["markets"]; bm = B[fid]["bookmakerOdds"]["betano.pt"]["markets"]
        for mid in set(pm) & set(bm):
            m = M.get(mid)
            if not m:
                continue
            n, h = m["name"], m["handicap"]
            if n == "Over Under Full Time": cat, kind = ("Golos 2,5" if h == 2.5 else "Outras linhas de golos"), "ou"
            elif n == "Full Time Result": cat, kind = "1X2", "1x2"
            elif n == "Both Teams To Score": cat, kind = "Ambas marcam", "btts"
            elif n == "Double Chance Full Time": cat, kind = "Dupla hipótese", "dc"
            elif n == "Draw No Bet": cat, kind = "Empate anula aposta", "dnb"
            elif n == "Corners - Over Under Full Time": cat, kind = "Cantos", "corners"
            elif n == "First Half Result": cat, kind = "1.ª parte", "ht1x2"
            elif n == "Over Under First Half": cat, kind = "1.ª parte", "htou"
            else:
                continue
            oids = list(m["outcomes"])
            pp = [price(pm[mid]["outcomes"].get(o)) for o in oids]; bp = [price(bm[mid]["outcomes"].get(o)) for o in oids]
            if None in pp or None in bp:
                continue
            fair = power_devig(pp)
            if not fair:
                continue
            counts.setdefault(d, {}); counts[d][cat] = counts[d].get(cat, 0) + len(oids)
            hs = fnum(h, 1).rstrip("0").rstrip(",") if h else ""
            for o, f, b in zip(oids, fair, bp):
                lab = m["outcomes"][o]
                if kind in ("1x2", "ht1x2"):
                    s = {"1": f"Vitória {home}", "X": "Empate", "2": f"Vitória {away}"}[lab]
                    aposta = ("1.ª parte: " if kind == "ht1x2" else "") + s
                elif kind == "ou": aposta = f"{'Mais' if lab == 'Over' else 'Menos'} de {hs} golos"
                elif kind == "htou": aposta = f"1.ª parte: {'mais' if lab == 'Over' else 'menos'} de {hs} golos"
                elif kind == "corners": aposta = f"{'Mais' if lab == 'Over' else 'Menos'} de {hs} cantos"
                elif kind == "btts": aposta = "Ambas marcam: " + ("sim" if lab == "Yes" else "não")
                elif kind == "dc": aposta = {"1X": f"{home} ou empate", "12": f"{home} ou {away}", "2X": f"Empate ou {away}"}[lab]
                else: aposta = f"{home if lab == '1' else away} (empate anula aposta)"
                ev = f * b - 1
                cls = "valor" if ev >= 0.05 else "marginal" if ev >= 0.02 else "nada"
                opts.append(dict(base, cat=cat, kind=kind, line=h, side=lab, aposta=aposta, fair=round(f, 4), odd=b,
                                 ev=round(ev, 4), cls=cls, casa="betano.pt", aviso=""))
    return opts, counts, {d: len(v) for d, v in games.items()}


# ---------------------------------------------------------------- The Odds API (1X2, várias casas)
def grp(title):
    t = title.lower()
    for k, v in [("unibet", "Unibet"), ("nordic", "Betsson"), ("betsson", "Betsson"), ("leovegas", "LeoVegas"),
                 ("winamax", "Winamax"), ("codere", "Codere"), ("betclic", "Betclic")]:
        if k in t:
            return v
    return title


odds_api_remaining = None


def odds_api(path, **params):
    global odds_api_remaining
    if not ODDS_API_KEY:
        return None
    if odds_api_remaining is not None and odds_api_remaining < ODDS_API_RESERVE:
        return None
    params["apiKey"] = ODDS_API_KEY
    d, h = http_json(f"https://api.the-odds-api.com/v4{path}?{urllib.parse.urlencode(params)}", 60)
    if h is not None and h.get("x-requests-remaining") is not None:
        odds_api_remaining = int(float(h["x-requests-remaining"]))
    return d


def build_intl(limit_date):
    opts, counts, games = [], {}, {}
    to = (NOW + timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for tid, cname, key, _ in COMPS:
        evs = odds_api(f"/sports/{key}/odds", regions="eu", markets="h2h", oddsFormat="decimal", commenceTimeTo=to)
        for e in evs or []:
            bk = {b["key"]: b for b in e["bookmakers"]}
            mk = lambda b: next((m for m in b["markets"] if m["key"] == "h2h"), None)
            if "pinnacle" not in bk or not mk(bk["pinnacle"]):
                continue
            t, quando = local(e["commence_time"])
            if t.date() > limit_date or t < NOW.astimezone(LIS):
                continue
            po = mk(bk["pinnacle"])["outcomes"]; names = [o["name"] for o in po]
            fair = power_devig([o["price"] for o in po])
            if not fair:
                continue
            fair = dict(zip(names, fair)); d = t.date().isoformat()
            games.setdefault(d, set()).add(e["id"]); counts[d] = counts.get(d, 0) + 3
            home, away = e["home_team"], e["away_team"]
            lab = {home: ("1", f"Vitória {home}"), away: ("2", f"Vitória {away}"), "Draw": ("X", "Empate")}
            for out in names:
                pr = sorted([({o["name"]: o["price"] for o in mk(b)["outcomes"]}.get(out), b["title"])
                             for k, b in bk.items() if k not in EXCH and mk(b)], key=lambda x: -(x[0] or 0))
                pr = [p for p in pr if p[0]]
                if not pr:
                    continue
                best = pr[0]; others = [p for p in pr if grp(p[1]) != grp(best[1])]
                if not others:
                    continue
                f = fair[out]; e1 = f * best[0] - 1; e2 = f * others[0][0] - 1
                cls = ("valor" if e1 >= 0.05 and e2 >= 0.02 else "marginal" if e1 >= 0.02 and e2 >= 0.02
                       else "desatualizada" if e1 >= 0.02 else "nada")
                casas = ", ".join(sorted({grp(p[1]) for p in pr if p[0] == best[0]}))
                aviso = (f"Também na {grp(others[0][1])} a {fnum(others[0][0])}" if cls in ("valor", "marginal")
                         else f"Só {casas} paga {fnum(best[0])}; a seguinte ({grp(others[0][1])}) paga {fnum(others[0][0])}" if cls == "desatualizada" else "")
                opts.append(dict(fid=e["id"], jogo=f"{home} – {away}", home=home, away=away, comp=cname, date=d, quando=quando,
                                 kickoff=e["commence_time"], cat="1X2", kind="1x2", line=0, side=lab[out][0], aposta=lab[out][1],
                                 fair=round(f, 4), odd=best[0], ev=round(e1, 4), cls=cls, casa=casas, aviso=aviso))
    log(f"The Odds API: {len(opts)} opções 1X2 (créditos restantes: {odds_api_remaining})")
    return opts, counts, {d: len(v) for d, v in games.items()}


# ---------------------------------------------------------------- exemplos e compactação
def favourites_example(opts, limit):
    xs = {}
    for o in opts:
        if o["cat"] == "1X2" and o["date"] <= limit:
            if o["jogo"] not in xs or o["fair"] > xs[o["jogo"]]["fair"]:
                xs[o["jogo"]] = o
    top = sorted(xs.values(), key=lambda o: -o["fair"])[:3]
    if len(top) < 3:
        return None
    off = math.prod(o["odd"] for o in top); p = math.prod(o["fair"] for o in top)
    eur = lambda e: ("+" if e >= 0 else "−") + fnum(abs(e) * 100) + " €"
    return dict(legs=[dict(sel=o["aposta"], jogo=f'{o["jogo"]} · {o["comp"]} · {o["quando"]}', justa=f'{round(o["fair"] * 100)}%',
                           min=fnum(1 / o["fair"]), odd=fnum(o["odd"]), vant=eur(o["fair"] * o["odd"] - 1)) for o in top],
                odd=fnum(off), justa=fnum(1 / p), prob=f"{round(p * 100)}%", ev=eur(p * off - 1), volta=round(p * off * 100))


def compact(opts):
    keep = set(i for i, o in enumerate(opts) if o["ev"] >= -0.03)
    by = {}
    for i, o in enumerate(opts):
        by.setdefault((o["date"], o["cat"]), []).append(i)
    for ix in by.values():
        keep |= set(sorted(ix, key=lambda i: -opts[i]["ev"])[:10])
    return [[o["date"], o["jogo"], o["comp"], o["quando"], o["cat"], o["aposta"], o["fair"], o["odd"], o["ev"], o["cls"], o["casa"], o["aviso"]]
            for i, o in enumerate(opts) if i in keep]


# ---------------------------------------------------------------- resultados
def fd_season(d):
    y = d.year % 100
    return f"{y:02d}{y + 1:02d}" if d.month >= 7 else f"{y - 1:02d}{y:02d}"


def load_results():
    rf = DATA / "results.json"
    res = json.loads(rf.read_text()) if rf.exists() else []
    seen = {(r["comp"], r["date"], r["home"], r["away"]) for r in res}
    # 6 ligas: football-data.co.uk (golos, intervalo e cantos)
    for tid, cname, key, code in COMPS:
        if not code:
            continue
        txt = http_text(f"https://www.football-data.co.uk/mmz4281/{fd_season(TODAY)}/{code}.csv")
        if not txt:
            continue
        for r in csv.DictReader(io.StringIO(txt)):
            try:
                dd = datetime.strptime(r["Date"], "%d/%m/%Y").date().isoformat()
                row = dict(comp=cname, date=dd, home=r["HomeTeam"], away=r["AwayTeam"], hg=int(r["FTHG"]), ag=int(r["FTAG"]),
                           hthg=int(r["HTHG"]) if r.get("HTHG") else None, htag=int(r["HTAG"]) if r.get("HTAG") else None,
                           corners=(int(r["HC"]) + int(r["AC"])) if r.get("HC") and r.get("AC") else None)
            except (ValueError, KeyError, TypeError):
                continue
            k = (row["comp"], row["date"], row["home"], row["away"])
            if k not in seen:
                res.append(row); seen.add(k)
    # competições europeias: The Odds API (só golos)
    for tid, cname, key, code in COMPS:
        if code:
            continue
        sc = odds_api(f"/sports/{key}/scores", daysFrom=3)
        for e in sc or []:
            if not e.get("completed") or not e.get("scores"):
                continue
            s = {x["name"]: int(x["score"]) for x in e["scores"]}
            t, _ = local(e["commence_time"])
            row = dict(comp=cname, date=t.date().isoformat(), home=e["home_team"], away=e["away_team"],
                       hg=s.get(e["home_team"]), ag=s.get(e["away_team"]), hthg=None, htag=None, corners=None)
            k = (row["comp"], row["date"], row["home"], row["away"])
            if None not in (row["hg"], row["ag"]) and k not in seen:
                res.append(row); seen.add(k)
    res = [r for r in res if r["date"] >= (TODAY - timedelta(days=60)).isoformat()]
    rf.write_text(json.dumps(res, ensure_ascii=False, indent=0))
    return res


def find_result(entry, results):
    best, score = None, 0.0
    for r in results:
        if r["comp"] != entry["comp"] or abs((datetime.fromisoformat(r["date"]) - datetime.fromisoformat(entry["date"])).days) > 1:
            continue
        sh, sa = sim(entry["home"], r["home"]), sim(entry["away"], r["away"])
        if max(sh, sa) < 0.85:          # pelo menos uma equipa tem de coincidir quase na perfeição
            continue
        if sh + sa > score:
            best, score = r, sh + sa
    return best if score >= 1.25 else None


def settle(e, r):
    """Devolve 1 (ganhou), 0 (perdeu), 0.5 (devolvido: empate anula) ou None (sem dados)."""
    k, side, line = e["kind"], e["side"], e["line"]
    hg, ag = r["hg"], r["ag"]
    if k == "1x2":
        return int({"1": hg > ag, "X": hg == ag, "2": hg < ag}[side])
    if k == "ou":
        return int((hg + ag > line) if side == "Over" else (hg + ag < line))
    if k == "btts":
        return int((hg > 0 and ag > 0) == (side == "Yes"))
    if k == "dc":
        return int({"1X": hg >= ag, "12": hg != ag, "2X": hg <= ag}[side])
    if k == "dnb":
        return 0.5 if hg == ag else int((hg > ag) if side == "1" else (hg < ag))
    if k in ("ht1x2", "htou"):
        if r.get("hthg") is None:
            return None
        h1, a1 = r["hthg"], r["htag"]
        if k == "ht1x2":
            return int({"1": h1 > a1, "X": h1 == a1, "2": h1 < a1}[side])
        return int((h1 + a1 > line) if side == "Over" else (h1 + a1 < line))
    if k == "corners":
        if r.get("corners") is None:
            return None
        return int((r["corners"] > line) if side == "Over" else (r["corners"] < line))
    return None


# ---------------------------------------------------------------- registo "daqui para a frente"
def update_tracker(all_opts, results):
    tf = DATA / "tracker_log.json"
    T = json.loads(tf.read_text()) if tf.exists() else {}
    for src, opts in all_opts.items():
        for o in opts:
            tested = o["cat"] in TESTED
            flagged = (tested and o["cls"] in ("valor", "marginal", "desatualizada")) or (not tested and o["ev"] >= 0.02)
            key = "|".join([src, o["fid"], o["cat"], o["aposta"]])
            if key in T:
                T[key]["last_fair"] = o["fair"]; T[key]["last_seen"] = NOW.isoformat(timespec="minutes")
                continue
            if not flagged:
                continue
            T[key] = dict(src=src, comp=o["comp"], date=o["date"], kickoff=o["kickoff"], jogo=o["jogo"], home=o["home"], away=o["away"],
                          cat=o["cat"], kind=o["kind"], line=o["line"], side=o["side"], aposta=o["aposta"], casa=o["casa"],
                          odd=o["odd"], fair=o["fair"], ev=o["ev"], grupo=(o["cls"] if tested else "desaconselhado"),
                          first_seen=NOW.isoformat(timespec="minutes"), last_fair=o["fair"], last_seen=NOW.isoformat(timespec="minutes"),
                          result=None, score=None)
    for e in T.values():
        if e["result"] is not None:
            continue
        if datetime.fromisoformat(e["kickoff"].replace("Z", "+00:00")) > NOW - timedelta(hours=3):
            continue
        r = find_result(e, results)
        if r:
            e["result"] = settle(e, r); e["score"] = f'{r["hg"]}-{r["ag"]}'
            if e["result"] is None:
                e["result"] = "sem dados"
    tf.write_text(json.dumps(T, ensure_ascii=False, indent=0))
    return T


def tracker_summary(T):
    groups = {"valor": "Vale a pena", "marginal": "Por pouco", "desatualizada": "Odd desatualizada", "desaconselhado": "Desaconselhado"}
    out = {}
    for g, nome in groups.items():
        xs = [e for e in T.values() if e["grupo"] == g]
        done = [e for e in xs if isinstance(e["result"], (int, float))]
        won = sum(1 for e in done if e["result"] == 1)
        pnl = sum((e["odd"] - 1) if e["result"] == 1 else (0 if e["result"] == 0.5 else -1) for e in done)
        better = [e for e in done if e["odd"] * e["last_fair"] > 1]
        out[g] = dict(nome=nome, total=len(xs), resolvidas=len(done), pendentes=len(xs) - len(done), acertos=won,
                      esperado=round(sum(e["fair"] for e in done), 1),
                      lucro100=round(pnl / len(done) * 100, 2) if done else None,
                      melhor=round(100 * len(better) / len(done)) if done else None)
    recent = sorted([e for e in T.values() if e["result"] is not None], key=lambda e: e["kickoff"], reverse=True)[:20]
    ult = []
    for e in recent:
        r = e["result"]
        ult.append(dict(jogo=e["jogo"], comp=e["comp"], quando=local(e["kickoff"])[1], aposta=e["aposta"], cat=e["cat"], casa=e["casa"],
                        odd=fnum(e["odd"]), grupo=groups[e["grupo"]], res=e["score"],
                        acertou=("Sim" if r == 1 else "Não" if r == 0 else "Devolvida" if r == 0.5 else "Sem dados"),
                        lucro=("+" + fnum(e["odd"] - 1) if r == 1 else "−1,00" if r == 0 else "0,00" if r == 0.5 else "—") + (" €" if r != "sem dados" else ""),
                        melhor=("Sim" if e["odd"] * e["last_fair"] > 1 else "Não")))
    return dict(grupos=out, ultimas=ult, desde=min((e["first_seen"] for e in T.values()), default=None))


# ---------------------------------------------------------------- principal
def main():
    OUT.mkdir(parents=True, exist_ok=True); DATA.mkdir(parents=True, exist_ok=True)
    limit = TODAY + timedelta(days=7)
    raw_pt = fetch_oddspapi()
    pf = OUT / "panel.json"
    prev = json.loads(pf.read_text()) if pf.exists() else {}
    if raw_pt:
        pt, cpt, gpt = build_pt(raw_pt, limit)
    else:
        pt, cpt, gpt = None, prev.get("countsPT", {}), prev.get("gamesPT", {})
    intl, cint, gint = build_intl(limit)

    labs, exPT, exIntl = {}, {}, {}
    for d in range(1, 8):
        lim = (TODAY + timedelta(days=d)).isoformat(); dd = TODAY + timedelta(days=d)
        labs[str(d)] = f"até {DIAS[dd.weekday()]}, {dd.day} {MESES[dd.month - 1]}"
        if pt: exPT[str(d)] = favourites_example(pt, lim)
        exIntl[str(d)] = favourites_example(intl, lim)
    panel = dict(generated=NOW.isoformat(timespec="minutes"), today=TODAY.isoformat(),
                 generatedTxt=local(NOW.isoformat())[1].replace(",", " às"),
                 dates=[(TODAY + timedelta(days=d)).isoformat() for d in range(0, 8)], labs=labs,
                 pt=compact(pt) if pt else prev.get("pt", []), countsPT=cpt, gamesPT=gpt,
                 intl=compact(intl), countsIntl=cint, gamesIntl=gint,
                 exPT=exPT if pt else prev.get("exPT", {}), exIntl=exIntl,
                 ptFresh=bool(pt), tested=sorted(TESTED), cats=CATS)
    pf.write_text(json.dumps(panel, ensure_ascii=False, separators=(",", ":")))

    results = load_results()
    T = update_tracker({"pt": pt or [], "intl": intl}, results)
    (OUT / "tracker.json").write_text(json.dumps(tracker_summary(T), ensure_ascii=False, separators=(",", ":")))
    log(f"Painel escrito: {len(panel['pt'])} opções betano.pt, {len(panel['intl'])} opções internacionais; registo: {len(T)} apostas")


if __name__ == "__main__":
    main()
