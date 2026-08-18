#!/usr/bin/env python3
"""Live-reloading preview server.

    python3 build/dev.py          (or: make dev)

Serves the site on http://localhost:8000, watches the sources, and reloads the
browser when anything changes. Drafts are included, so you can see a \\draft
post while writing it.

What gets rebuilt depends on what you touched, because LaTeXML is the slow
part and there is no reason to pay for it twice:

    content/*.tex      just that page, plus the index and sitemap
    lib/*.sty          everything -- a macro change can affect any page
    build/*.py         everything, including the template
    assets/*           nothing; the files are copied and the page reloads

Build errors don't kill the server. The last good site stays up and the error
appears as a banner in the browser, so a typo in a \\begin doesn't leave you
staring at a blank page wondering if the server died.

Stdlib only, matching the rest of the build: the reload channel is a small
JSON endpoint the page polls, and the client script is injected into HTML
responses as they are served rather than baked into the template -- so nothing
about the published output changes.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build as B                                        # noqa: E402

ROOT = B.ROOT
POLL_SECONDS = 0.35

# Globs watched for changes, and what a change to each implies.
WATCH = {
    "content": ["content/**/*.tex", "content/**/*.bib"],
    "lib":     ["lib/*.sty"],
    "build":   ["build/*.py", "build/templates/*"],
    "assets":  ["assets/**/*"],
}

RELOAD_JS = """
<script>
/* injected by build/dev.py -- not present in the published site */
(function () {
  var known = null, banner = null;

  function show(msg) {
    if (!msg) { if (banner) { banner.remove(); banner = null; } return; }
    if (!banner) {
      banner = document.createElement('pre');
      banner.style.cssText =
        'position:fixed;left:0;right:0;bottom:0;z-index:99999;margin:0;' +
        'max-height:45vh;overflow:auto;padding:14px 18px;' +
        'background:#2b0f0f;color:#ffd9d2;font:12px/1.5 ui-monospace,monospace;' +
        'white-space:pre-wrap;border-top:3px solid #d4573f;';
      document.body.appendChild(banner);
    }
    banner.textContent = 'build failed\\n\\n' + msg;
  }

  function tick() {
    fetch('/__dev', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (known === null) known = d.id;
        else if (d.id !== known) { location.reload(); return; }
        show(d.error);
      })
      .catch(function () { /* server restarting; try again */ })
      .then(function () { setTimeout(tick, %d); });
  }
  tick();
})();
</script>
""" % int(POLL_SECONDS * 1000)


class State:
    """Shared between the watcher thread and the request handlers."""

    def __init__(self):
        self.build_id = 0
        self.error = None
        self.lock = threading.Lock()   # keeps requests out of a partial build


STATE = State()


# ---------------------------------------------------------------------------
# Watching
# ---------------------------------------------------------------------------

def snapshot() -> dict[Path, float]:
    seen = {}
    for globs in WATCH.values():
        for pattern in globs:
            for f in ROOT.glob(pattern):
                if f.is_file():
                    try:
                        seen[f] = f.stat().st_mtime
                    except OSError:
                        pass
    return seen


def classify(changed: set[Path]) -> tuple[str, set[Path]]:
    """Decide how much to rebuild. Returns (scope, changed content sources)."""
    def under(kind):
        return any(f in set(ROOT.glob(p)) for p in WATCH[kind] for f in changed)

    if under("lib") or under("build"):
        return "full", set()
    content = {f for f in changed if f.suffix in (".tex", ".bib")
               and B.CONTENT in f.parents}
    if content:
        # A .bib is shared by the posts that cite it, so play safe and do all.
        if any(f.suffix == ".bib" for f in content):
            return "full", set()
        return "pages", content
    return "assets", set()


def rebuild(scope: str, sources: set[Path], drafts: bool):
    started = time.time()
    label = {"full": "rebuilding everything",
             "pages": "rebuilding " + ", ".join(sorted(s.name for s in sources)),
             "assets": "syncing assets"}[scope]
    print(f"  {label} ... ", end="", flush=True)

    with STATE.lock:
        try:
            if scope == "assets":
                B.sync_assets()
            else:
                B.build(drafts=drafts, quiet=True,
                        only=None if scope == "full" else sources)
            STATE.error = None
            print(f"ok ({time.time() - started:.1f}s)")
        except B.BuildError as e:
            STATE.error = str(e)
            print("failed")
            print(f"    {e}".replace("\n", "\n    "))
        except Exception:                      # a bug in the build itself
            STATE.error = traceback.format_exc()
            print("crashed")
            traceback.print_exc()
        STATE.build_id += 1


def watch(drafts: bool):
    previous = snapshot()
    while True:
        time.sleep(POLL_SECONDS)
        current = snapshot()
        changed = {f for f, t in current.items()
                   if previous.get(f) != t} | (set(previous) - set(current))
        if changed:
            # Let a burst of writes (an editor saving several files) settle.
            time.sleep(0.15)
            current = snapshot()
            scope, sources = classify(changed)
            rebuild(scope, sources, drafts)
        previous = current


# ---------------------------------------------------------------------------
# Serving
# ---------------------------------------------------------------------------

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(B.OUT), **kw)

    def log_message(self, fmt, *args):
        pass                                   # the rebuild log is the useful one

    def _send(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/__dev":
            with STATE.lock:
                payload = {"id": STATE.build_id, "error": STATE.error}
            self._send(json.dumps(payload).encode(), "application/json")
            return

        # Serve HTML ourselves so the reload script can be injected, and so a
        # request never reads a file mid-rebuild.
        with STATE.lock:
            path = self.translate_path(self.path)
            if os.path.isdir(path):
                path = os.path.join(path, "index.html")
            if path.endswith(".html") and os.path.isfile(path):
                html = Path(path).read_text(encoding="utf-8")
                if "</body>" in html:
                    html = html.replace("</body>", RELOAD_JS + "</body>", 1)
                else:
                    html += RELOAD_JS
                self._send(html.encode("utf-8"), "text/html; charset=utf-8")
                return
        super().do_GET()


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(port: int, host: str):
    for candidate in range(port, port + 20):
        try:
            return Server((host, candidate), Handler), candidate
        except OSError as e:
            if e.errno not in (98, 48):        # address already in use
                raise
    raise SystemExit(f"no free port in {port}-{port + 19}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="default is localhost only; use 0.0.0.0 to expose "
                         "the preview on your network")
    ap.add_argument("--no-drafts", action="store_true",
                    help="hide \\draft pages, as the published build does")
    args = ap.parse_args()

    drafts = not args.no_drafts

    print("building ... ", end="", flush=True)
    try:
        B.build(drafts=drafts, quiet=True)
        print("ok")
    except B.BuildError as e:
        STATE.error = str(e)
        print(f"failed\n  {e}")

    httpd, port = serve(args.port, args.host)
    threading.Thread(target=watch, args=(drafts,), daemon=True).start()

    print(f"\n  http://{args.host}:{port}"
          f"{'  (drafts included)' if drafts else ''}")
    print("  watching content/, lib/, assets/, build/ -- ctrl-c to stop\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
