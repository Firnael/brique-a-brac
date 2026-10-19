#!/usr/bin/env python3
"""lego-bordel: picking lists by color for rebuilding LEGO sets from a mixed pile.

Stdlib only. Data lives in ./data (cache of Rebrickable responses + state.json).
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
CACHE = DATA / "cache"
STATE_FILE = DATA / "state.json"
STATIC = ROOT / "static"
API = "https://rebrickable.com/api/v3/lego"
PORT = int(os.environ.get("PORT", "8642"))


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
KEY = os.environ.get("REBRICKABLE_API_KEY", "")
lock = threading.Lock()
rate_lock = threading.Lock()
_last_call = [0.0]


# --- Rebrickable ------------------------------------------------------------

def rb_get(url):
    # Rebrickable allows ~1 req/s
    with rate_lock:
        wait = 1.05 - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
    req = urllib.request.Request(url, headers={"Authorization": f"key {KEY}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def rb_paged(url):
    out = []
    while url:
        page = rb_get(url)
        out += page["results"]
        url = page.get("next")
    return out


def cached(name, fetch):
    path = CACHE / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    data = fetch()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def colors():
    return cached("colors", lambda: {
        c["id"]: {"id": c["id"], "name": c["name"], "rgb": c["rgb"], "is_trans": c["is_trans"]}
        for c in rb_paged(f"{API}/colors/?page_size=1000")
    })


def bl_colors():
    """BrickLink color id -> Rebrickable color id (Brickognize speaks BrickLink)."""
    return cached("bl_colors", lambda: {
        str(bl): c["id"]
        for c in rb_paged(f"{API}/colors/?page_size=1000")
        for bl in (c.get("external_ids", {}).get("BrickLink", {}).get("ext_ids") or [])
    })


def themes():
    def fetch():
        raw = {t["id"]: t for t in rb_paged(f"{API}/themes/?page_size=1000")}
        out = {}
        for tid, t in raw.items():
            root = t
            while root.get("parent_id") in raw:
                root = raw[root["parent_id"]]
            out[str(tid)] = root["name"] if root is t else f"{root['name']} › {t['name']}"
        return out
    return cached("themes", fetch)


def categories():
    return cached("part_categories", lambda: {
        c["id"]: c["name"] for c in rb_paged(f"{API}/part_categories/?page_size=1000")
    })


def fetch_set(set_num):
    info = rb_get(f"{API}/sets/{set_num}/")
    rows = rb_paged(f"{API}/sets/{set_num}/parts/?page_size=1000&inc_minifig_parts=1")
    parts = {}
    for r in rows:
        if r["is_spare"]:
            continue
        p, c = r["part"], r["color"]
        key = f"{p['part_num']}|{c['id']}"
        if key in parts:  # same part listed twice (set + minifig)
            parts[key]["qty"] += r["quantity"]
            continue
        bl_color = c.get("external_ids", {}).get("BrickLink", {}).get("ext_ids") or [None]
        parts[key] = {
            "key": key,
            "part_num": p["part_num"],
            "name": p["name"],
            "cat": p["part_cat_id"],
            "img": p["part_img_url"],
            "url": p["part_url"],
            "color": c["id"],
            "qty": r["quantity"],
            "bl_part": (p.get("external_ids", {}).get("BrickLink") or [p["part_num"]])[0],
            "bl_color": bl_color[0],
        }
    return {
        "set_num": info["set_num"],
        "name": info["name"],
        "year": info["year"],
        "num_parts": info["num_parts"],
        "img": info["set_img_url"],
        "url": info["set_url"],
        "parts": list(parts.values()),
    }


def get_set(set_num):
    return cached(f"set_{set_num}", lambda: fetch_set(set_num))


# --- LEGO building instructions ---------------------------------------------

BOOKLET_RE = re.compile(
    r'"isAdditionalInfoBooklet":(true|false),"sequence":\{[^}]*"total":"(\d+)","element":"(\d+)"\},'
    r'"pdf":\{"__typename":"PDF","coverImage":\{[^}]*"src":"([^"]+)"[^}]*\},'
    r'"pdfUrl":"https://www\.lego\.com/cdn/product-assets/product\.bi\.core\.pdf/(\d+)\.pdf"')


def fetch_instructions(set_num):
    lego_num = re.sub(r"-1$", "", set_num)
    req = urllib.request.Request(f"https://www.lego.com/en-us/service/building-instructions/{lego_num}",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        page = r.read().decode("utf-8", "replace")
    booklets, seen = [], set()
    for extra, total, element, cover, pdf_id in BOOKLET_RE.findall(page):
        if pdf_id in seen:
            continue
        seen.add(pdf_id)
        booklets.append({"id": pdf_id, "cover": cover, "element": int(element), "total": int(total),
                         "extra": extra == "true"})
    booklets.sort(key=lambda b: (b["extra"], b["element"]))
    return booklets


def get_instructions(set_num):
    try:
        return cached(f"bi_{set_num}", lambda: fetch_instructions(set_num))
    except Exception:
        return []


def notice_pdf(pdf_id):
    path = CACHE / "pdf" / f"{pdf_id}.pdf"
    if not path.exists():
        req = urllib.request.Request(f"https://www.lego.com/cdn/product-assets/product.bi.core.pdf/{pdf_id}.pdf",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path.read_bytes()


# --- State ------------------------------------------------------------------
# state = {"queue": [set_num, ...], "done": [set_num, ...], "picked": {set_num: {key: n}}}

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"queue": [], "done": [], "picked": {}}


def save_state(s):
    DATA.mkdir(parents=True, exist_ok=True)
    backup_state()
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1))
    tmp.replace(STATE_FILE)


def backup_state(keep=14):
    """Before the first write of the day, copy state.json to backups/; keep the last `keep` days."""
    if not STATE_FILE.exists():
        return
    backups = DATA / "backups"
    today = backups / f"state-{time.strftime('%Y-%m-%d')}.json"
    if today.exists():
        return
    backups.mkdir(exist_ok=True)
    today.write_bytes(STATE_FILE.read_bytes())
    for old in sorted(backups.glob("state-*.json"))[:-keep]:
        old.unlink()


def norm_set(n):
    n = n.strip()
    return n if re.search(r"-\d+$", n) else f"{n}-1"


def full_state():
    s = load_state()
    sets = [dict(get_set(n), notices=get_instructions(n)) for n in s["queue"]]
    used = {p["color"] for st in sets for p in st["parts"]}
    return {
        "queue": s["queue"],
        "done": s["done"],
        "picked": s["picked"],
        "clues": s.get("clues", []),
        "sets": {st["set_num"]: st for st in sets},
        "colors": colors(),
        "used_colors": sorted(used),
        "categories": categories(),
    }


def pick(key, delta, set_num=None):
    """+1: give the piece to the first active set (queue order) still missing it.
    -1: take it back from the last set holding it (or from set_num if given)."""
    s = load_state()
    active = [n for n in s["queue"] if n not in s["done"]]
    target = None
    if delta > 0:
        for n in ([set_num] if set_num else active):
            need = sum(p["qty"] for p in get_set(n)["parts"] if p["key"] == key)
            if s["picked"].get(n, {}).get(key, 0) < need:
                target = n
                break
    else:
        for n in ([set_num] if set_num else reversed(active)):
            if s["picked"].get(n, {}).get(key, 0) > 0:
                target = n
                break
    if target:
        bag = s["picked"].setdefault(target, {})
        bag[key] = bag.get(key, 0) + delta
        if bag[key] <= 0:
            del bag[key]
        save_state(s)
    return target


def missing(set_num):
    s = load_state()
    st = get_set(set_num)
    got = s["picked"].get(set_num, {})
    return [(p, p["qty"] - got.get(p["key"], 0)) for p in st["parts"] if p["qty"] > got.get(p["key"], 0)]


def missing_bricklink(set_nums):
    """One BrickLink wanted list for several sets, quantities merged."""
    merged = {}
    for n in set_nums:
        for p, qty in missing(n):
            k = (p["bl_part"], p["bl_color"])
            merged[k] = merged.get(k, 0) + qty
    items = "".join(
        f"<ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>{part}</ITEMID>"
        + (f"<COLOR>{color}</COLOR>" if color is not None else "")
        + f"<MINQTY>{qty}</MINQTY></ITEM>"
        for (part, color), qty in merged.items()
    )
    return f"<INVENTORY>{items}</INVENTORY>\n"


# --- Identification (Brickognize photo -> part -> candidate sets) -------------

def brickognize(image):
    boundary = f"----lego{int(time.time() * 1000)}"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"query_image\"; filename=\"part.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n").encode() + image + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        "https://api.brickognize.com/predict/parts/?predict_color=true&top_k_items=5&top_k_colors=5",
        data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def rb_part_from_bricklink(bl_id):
    def fetch():
        res = rb_get(f"{API}/parts/?bricklink_id={urllib.parse.quote(bl_id)}")["results"]
        if res:
            return res[0]["part_num"]
        try:
            return rb_get(f"{API}/parts/{urllib.parse.quote(bl_id)}/")["part_num"]
        except urllib.error.HTTPError:
            return None
    return cached(f"blpart_{re.sub(r'[^\w.-]', '_', bl_id)}", fetch)


def part_colors(part_num):
    """Colors a part exists in, most common first."""
    rows = cached(f"pc_{part_num}", lambda: rb_paged(f"{API}/parts/{urllib.parse.quote(part_num)}/colors/?page_size=1000"))
    rows = sorted(rows, key=lambda r: -r["num_sets"])
    return [{"color": r["color_id"], "num_sets": r["num_sets"], "img": r["part_img_url"]} for r in rows]


def identify(image):
    res = brickognize(image)
    blc = bl_colors()
    predicted = [blc[c["id"]] for c in res.get("colors", []) if c["id"] in blc]
    items = []
    for it in res.get("items", [])[:5]:
        part = rb_part_from_bricklink(it["id"])
        if part:
            items.append({"part_num": part, "bl_id": it["id"], "name": it["name"], "img": it["img_url"],
                          "score": round(it["score"], 2)})
    return {"items": items, "colors": predicted}


def part_sets(part_num, color):
    return cached(f"ps_{part_num}_{color}", lambda: [
        {k: r[k] for k in ("set_num", "name", "year", "theme_id", "num_parts", "set_img_url", "set_url")}
        for r in rb_paged(f"{API}/parts/{urllib.parse.quote(part_num)}/colors/{color}/sets/?page_size=1000")
    ])


def candidates(clues):
    """Sets containing the most clues first; ties broken by year."""
    th = themes()
    found = {}
    for c in clues:
        for s in part_sets(c["part_num"], c["color"]):
            e = found.setdefault(s["set_num"], dict(s, theme=th.get(str(s["theme_id"]), ""), matches=0))
            e["matches"] += 1
    ranked = sorted((s for s in found.values() if s["num_parts"] > 0),
                    key=lambda s: (-s["matches"], s["year"]))
    return {"total": len(ranked), "sets": ranked[:60]}


# --- HTTP -------------------------------------------------------------------

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(STATIC), **kw)

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else (
            body.encode() if isinstance(body, str) else json.dumps(body).encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        try:
            if self.path == "/api/state":
                with lock:
                    return self.send(200, full_state())
            m = re.fullmatch(r"/api/notice/(\d+)\.pdf", self.path)
            if m:
                return self.send(200, notice_pdf(m.group(1)), "application/pdf",
                                 {"Content-Disposition": f'inline; filename="notice_{m.group(1)}.pdf"'})
            url = urllib.parse.urlsplit(self.path)
            if url.path == "/api/missing.xml":
                sets = urllib.parse.parse_qs(url.query).get("sets", [""])[0].split(",")
                with lock:
                    body = missing_bricklink([n for n in sets if n in load_state()["queue"]])
                return self.send(200, body, "application/xml",
                                 {"Content-Disposition": 'attachment; filename="wanted_list_bricklink.xml"'})
            m = re.fullmatch(r"/api/part_colors/([\w.-]+)", self.path)
            if m:
                return self.send(200, part_colors(m.group(1)))
            if self.path == "/api/candidates":
                return self.send(200, candidates(load_state().get("clues", [])))
        except Exception as e:
            return self.send(500, {"error": str(e)})
        return super().do_GET()

    def do_POST(self):
        try:
            if self.path == "/api/identify":
                image = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                return self.send(200, identify(image))
            b = self.body()
            with lock:
                s = load_state()
                if self.path == "/api/sets":
                    n = norm_set(b["set_num"])
                    try:
                        get_set(n)
                        get_instructions(n)
                    except urllib.error.HTTPError as e:
                        if e.code == 404:
                            return self.send(404, {"error": f"Set {n} introuvable sur Rebrickable"})
                        raise
                    if n not in s["queue"]:
                        s["queue"].append(n)
                        save_state(s)
                    return self.send(200, {"ok": True, "set_num": n})
                if self.path == "/api/remove":
                    n = b["set_num"]
                    s["queue"] = [x for x in s["queue"] if x != n]
                    s["done"] = [x for x in s["done"] if x != n]
                    s["picked"].pop(n, None)
                    save_state(s)
                    return self.send(200, {"ok": True})
                if self.path == "/api/order":
                    if sorted(b["queue"]) == sorted(s["queue"]):
                        s["queue"] = b["queue"]
                        save_state(s)
                    return self.send(200, {"ok": True})
                if self.path == "/api/done":
                    n = b["set_num"]
                    s["done"] = [x for x in s["done"] if x != n] + ([n] if b["done"] else [])
                    save_state(s)
                    return self.send(200, {"ok": True})
                if self.path == "/api/pick":
                    target = pick(b["key"], 1 if b["delta"] > 0 else -1, b.get("set_num"))
                    return self.send(200, {"set_num": target})
                if self.path == "/api/clues":
                    clue = {k: b[k] for k in ("part_num", "color", "name", "img")}
                    clues = s.setdefault("clues", [])
                    if not any(c["part_num"] == clue["part_num"] and c["color"] == clue["color"] for c in clues):
                        clues.append(clue)
                        save_state(s)
                    return self.send(200, {"ok": True})
                if self.path == "/api/clues/remove":
                    clues = s.get("clues", [])
                    if 0 <= b["index"] < len(clues):
                        del clues[b["index"]]
                        save_state(s)
                    return self.send(200, {"ok": True})
                if self.path == "/api/clues/clear":
                    s["clues"] = []
                    save_state(s)
                    return self.send(200, {"ok": True})
        except Exception as e:
            return self.send(500, {"error": str(e)})
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    if not KEY:
        raise SystemExit("REBRICKABLE_API_KEY manquante (.env ou variable d'environnement)")
    print(f"lego-bordel sur http://0.0.0.0:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
