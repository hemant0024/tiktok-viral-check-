"""Bakes the live dashboard into one file that opens with a double click.

The served dashboard needs python, the right PYTHONPATH and a running process.
This one needs a browser. Same page, same code, with the API responses frozen
into it and fetch pointed at them instead of at a server.
"""
import json, pathlib, sys
sys.path.insert(0, "src")

from ci.config import get_settings
from ci.database import get_repository
from ci.dashboard import api

settings = get_settings()
repo = get_repository(settings)

baked = {
    "/api/health": api.health(settings, repo),
    "/api/config": api.config(settings),
    "/api/cost":   api.cost(settings),
    "/api/facets": api.facets(settings, repo),
    "/api/rows":   api.rows(settings, repo, limit=5000),
}

page = pathlib.Path("src/ci/dashboard/page.html").read_text()

shim = """
<script>
/* ---- offline copy -------------------------------------------------------
   Every API answer below was frozen at build time. fetch is redirected at
   them, so the page runs exactly as it does against the server, minus the
   things that genuinely need one: running jobs and saving settings. Those
   say so rather than failing silently.                                   */
window.__BAKED__ = %s;
window.__BAKED_AT__ = %s;
(function(){
  const real = window.fetch;
  const NUM = {min_score:["radar_score","ge"], max_score:["radar_score","le"],
    min_views:["views","ge"], max_views:["views","le"],
    min_age:["age_hours","ge"], max_age:["age_hours","le"],
    min_share_rate:["share_rate","ge"], max_followers:["creator_followers","le"]};
  const num = (r,f) => { const v = Number(r[f]); return isFinite(v) ? v : 0; };

  function filterRows(url){
    const all = window.__BAKED__["/api/rows"].rows;
    const q = new URLSearchParams((url.split("?")[1] || ""));
    const list = k => new Set((q.get(k) || "").split(",").filter(Boolean));
    const tiers = new Set([...list("tiers")].map(t => t.toUpperCase()));
    const comps = list("competitors");
    const stats = new Set([...list("statuses")].map(t => t.toUpperCase()));
    const date = q.get("date") || "";
    const text = (q.get("q") || "").toLowerCase().trim();

    let out = all.filter(r => {
      if(tiers.size && !tiers.has(String(r.takeoff_tier || "").toUpperCase())) return false;
      if(comps.size && !comps.has(r.competitor)) return false;
      if(stats.size && !stats.has(String(r.status || "").toUpperCase())) return false;
      if(date && r.date !== date) return false;
      if(q.get("jackpot_only") && !r.is_jackpot) return false;
      if(text && ![r.title, r.creator, r.competitor].join(" ").toLowerCase().includes(text)) return false;
      for(const [key, [field, op]] of Object.entries(NUM)){
        const raw = q.get(key);
        if(raw === null || raw === "") continue;
        const bound = Number(raw), value = num(r, field);
        if(op === "ge" ? value < bound : value > bound) return false;
      }
      return true;
    });
    const sort = q.get("sort") || "radar_score";
    const dir = q.get("ascending") ? 1 : -1;
    out = out.slice().sort((a, b) => (num(a, sort) - num(b, sort)) * dir);
    const limit = Number(q.get("limit") || 200);
    return {total: all.length, matched: out.length, rows: out.slice(0, limit)};
  }

  window.fetch = function(input, init){
    const url = String(typeof input === "string" ? input : input.url);
    const path = url.split("?")[0].replace(/^https?:\\/\\/[^/]+/, "");
    const method = (init && init.method) || "GET";
    const reply = (code, body) => Promise.resolve(new Response(
      JSON.stringify(body), {status: code, headers: {"Content-Type": "application/json"}}));

    if(method === "POST"){
      if(path.startsWith("/api/run/")) return reply(409, {error:
        "This is the offline copy, so it cannot collect or score. Run ./dashboard.sh in the project folder for the live one."});
      if(path === "/api/config") return reply(400, {error:
        "The offline copy cannot write to your config files. Run ./dashboard.sh to change settings for real."});
      if(path === "/api/preview") return reply(200, {moved: [], note: "offline"});
    }
    if(path === "/api/run") return reply(200, {jobs: [], running: null, label: null,
      elapsed: null, steps: [], last: null, history: []});
    if(path === "/api/rows") return reply(200, filterRows(url));
    if(window.__BAKED__[path]) return reply(200, window.__BAKED__[path]);
    if(typeof real === "function") return real.apply(this, arguments);
    return reply(404, {error: "not found"});
  };
})();
</script>
""" % (json.dumps(baked, default=str), json.dumps(
    __import__("datetime").datetime.now().strftime("%d %b %Y, %H:%M")))

# The banner has to be visible. A frozen dashboard that looks live is how you
# end up reading Thursday's numbers on Monday.
banner = """
<div id="offline" style="position:sticky;top:0;z-index:100;display:flex;gap:10px;
  align-items:center;justify-content:center;padding:7px 14px;font-size:12px;
  background:#ffb020;color:#1a1204;font-weight:600">
  <span>Offline copy, frozen __WHEN__. Filters, sorting and the plot all work.
  Running jobs and saving settings need the live one: <code
  style="background:rgba(0,0,0,.14);padding:1px 6px;border-radius:4px">./dashboard.sh</code></span>
</div>
"""

out = page.replace("<script>\nconst $  =", shim + "<script>\nconst $  =", 1)
assert shim in out, "could not inject the shim"
out = out.replace("<body>", "<body>" + banner.replace("__WHEN__", baked["/api/rows"] and
                  __import__("datetime").datetime.now().strftime("%d %b %Y, %H:%M")), 1)
# The run button has nothing to offer here, so hide it with CSS. Taking it out
# of the markup breaks the page: the wiring script does $("#b-run").onclick=...
# and the null reference kills every line of setup after it.
out = out.replace("</head>",
    "<style>#b-run{display:none!important}</style>\n</head>", 1)

dest = pathlib.Path("radar-dashboard.html")
dest.write_text(out)
print("written", dest, f"{dest.stat().st_size/1024:.0f} KB",
      "|", baked["/api/rows"]["total"], "videos baked in")
