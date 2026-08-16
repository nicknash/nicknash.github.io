#!/usr/bin/env python3
"""Build the site: LaTeX sources in content/ become HTML pages in _site/.

The pipeline, per source file:

    1. Pull every tikzpicture out of the source and compile it on its own with
       LuaLaTeX, then convert the DVI to SVG with dvisvgm. Results are cached
       by content hash, so an unchanged figure is never rebuilt.
    2. Rewrite the source so each picture becomes an \\includegraphics of the
       SVG, and mark it as an HTML build so ghb.sty skips loading TikZ.
    3. Convert with latexml + latexmlpost to HTML5 with MathML.
    4. Lift the body out of LaTeXML's page furniture, inline the figure SVGs,
       and wrap the result in the site template.

Step 4 inlines rather than linking the SVGs for two reasons: it lets the
diagrams inherit the page's text colour through `currentColor` (so they work
in both themes), and it avoids a second network round-trip per figure.

Usage:  python3 build/build.py [--clean] [--serve]
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
LIB = ROOT / "lib"
ASSETS = ROOT / "assets"
BUILD = ROOT / "build"
OUT = ROOT / "_site"
CACHE = ROOT / ".cache"
FIGCACHE = CACHE / "figures"

# The standalone class used for figures defaults to a 10pt document, so a
# figure's width in TeX points divided by this gives its width in em.
TEX_PT_PER_EM = 10.0

SITE = {
    "title": "Nick",
    "url": "https://nicknash.github.io",
    "description": "Notes on graphs, algorithms and whatever else is holding "
                   "my attention.",
}

# Nav order is explicit rather than derived, so adding a post never silently
# rearranges the header.
NAV = [("/", "Home"), ("/posts/", "Posts")]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

class BuildError(RuntimeError):
    pass


def run(cmd, cwd=None, env=None, what="command"):
    """Run a subprocess, raising with captured output if it fails."""
    proc = subprocess.run(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stdout.strip().splitlines()[-40:])
        raise BuildError(f"{what} failed (exit {proc.returncode}):\n{tail}")
    return proc.stdout


def tex_env():
    """Environment with lib/ on TEXINPUTS so \\usepackage{ghb} resolves."""
    env = os.environ.copy()
    # The trailing ':' preserves the default search path.
    env["TEXINPUTS"] = f"{LIB}:{CONTENT}:" + env.get("TEXINPUTS", "")
    env["max_print_line"] = "1000"
    return env


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Reading metadata out of the .tex source
# ---------------------------------------------------------------------------

def brace_arg(src: str, cmd: str):
    r"""Return the argument of \cmd{...}, honouring nested braces.

    Returns None when the command is absent. A regex would get this wrong the
    moment a title contains a group, e.g. \title{On $\set{a,b}$ covers}.
    """
    m = re.search(r"\\" + cmd + r"\s*\{", src)
    if not m:
        return None
    i = m.end()
    depth, start = 1, i
    while i < len(src) and depth:
        c = src[i]
        if c == "\\":            # skip escaped char, incl. \{ and \}
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    if depth:
        raise BuildError(rf"unbalanced braces in \{cmd}")
    return src[start:i - 1].strip()


def has_command(src: str, cmd: str) -> bool:
    return re.search(r"\\" + cmd + r"(?![a-zA-Z])", src) is not None


def strip_tex(s: str) -> str:
    r"""Reduce a short TeX fragment to plain text, for <title> and meta tags.

    Deliberately crude: it only has to cope with titles and summaries, where
    the realistic worst case is \emph{...} or an inline $x$.
    """
    if s is None:
        return ""
    s = re.sub(r"\\(?:emph|textit|textbf|texttt|textsc)\s*\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\$([^$]*)\$", r"\1", s)
    s = re.sub(r"\\[a-zA-Z]+\s*", "", s)
    s = s.replace("{", "").replace("}", "").replace("~", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


@dataclass
class Page:
    src: Path
    slug: str
    kind: str                     # "page" or "post"
    title: str = ""
    date: date | None = None
    summary: str = ""
    draft: bool = False
    body: str = ""
    out_dir: Path = field(default=None)

    @property
    def url(self) -> str:
        return "/" if self.slug == "index" else f"/{self.slug}/"


def load_metadata(page: Page) -> Page:
    src = read(page.src)
    page.title = brace_arg(src, "title") or page.slug.replace("-", " ").title()
    page.summary = brace_arg(src, "summary") or ""
    page.draft = has_command(src, "draft")

    raw_date = brace_arg(src, "date")
    if raw_date:
        try:
            page.date = datetime.strptime(raw_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise BuildError(
                f"{page.src.name}: \\date must be ISO format YYYY-MM-DD, "
                f"got {raw_date!r} (the posts index sorts on it)"
            )
    elif page.kind == "post":
        # Fall back to a leading date in the filename, which is the convention
        # this site uses for posts.
        m = re.match(r"(\d{4}-\d{2}-\d{2})-", page.src.stem)
        if m:
            page.date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        else:
            raise BuildError(
                f"{page.src.name}: a post needs a date, either \\date{{...}} "
                f"or a YYYY-MM-DD- filename prefix"
            )
    return page


# ---------------------------------------------------------------------------
# Stage 1: figures
# ---------------------------------------------------------------------------

TIKZ_RE = re.compile(
    r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", re.DOTALL
)

STANDALONE = r"""\documentclass[dvisvgm,tikz,border=%(border)s]{standalone}
\def\ghbFigure{}
\usepackage{ghbtikz}
\begin{document}
%(body)s
\end{document}
"""


def figure_signature(code: str) -> str:
    """Hash the picture together with everything that affects how it renders.

    Including the style files means editing a \\tikzset in ghbtikz.sty
    correctly invalidates every cached figure, rather than leaving stale SVGs
    that no longer match the house style.
    """
    h = hashlib.sha256()
    h.update(code.encode())
    for sty in ("ghbtikz.sty", "ghbmath.sty"):
        h.update((LIB / sty).read_bytes())
    return h.hexdigest()[:16]


def render_figure(code: str, sig: str, verbose=False) -> Path:
    """Compile one tikzpicture to SVG. Cached on `sig`."""
    cached = FIGCACHE / f"{sig}.svg"
    if cached.exists():
        return cached

    FIGCACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ghbfig-") as td:
        td = Path(td)
        tex = td / "fig.tex"
        tex.write_text(STANDALONE % {"border": "2pt", "body": code},
                       encoding="utf-8")

        run(["lualatex", "--output-format=dvi", "-interaction=nonstopmode",
             "-halt-on-error", "-output-directory", str(td), str(tex)],
            cwd=td, env=tex_env(), what=f"lualatex on figure {sig}")

        # --currentcolor turns pure black into `currentColor`, which is what
        # lets a diagram follow the page's text colour in dark mode.
        # --exact-bbox measures the real ink rather than trusting TeX's box.
        run(["dvisvgm", "--exact-bbox", "--font-format=woff2",
             "--currentcolor=#000000", "--optimize=all", "--no-fonts=0",
             "-o", str(cached), str(td / "fig.dvi")],
            cwd=td, what=f"dvisvgm on figure {sig}")

    if verbose:
        print(f"      figure {sig} rendered")
    return cached


def extract_figures(src: str, verbose=False):
    """Replace each tikzpicture with an \\includegraphics of its SVG.

    Returns the rewritten source and a {signature: svg_path} map.
    """
    figures = {}

    def sub(m):
        code = m.group(0)
        sig = figure_signature(code)
        if sig not in figures:
            figures[sig] = render_figure(code, sig, verbose)
        # A relative path keeps LaTeXML from rewriting it into something
        # absolute; we substitute the real SVG back in during post-processing.
        return rf"\includegraphics{{ghbfig-{sig}.svg}}"

    return TIKZ_RE.sub(sub, src), figures


# ---------------------------------------------------------------------------
# Stage 2: LaTeXML
# ---------------------------------------------------------------------------

def convert(page: Page, rewritten: str, figures: dict, verbose=False) -> str:
    """Run latexml/latexmlpost over the rewritten source, return raw HTML."""
    with tempfile.TemporaryDirectory(prefix="ghbdoc-") as td:
        td = Path(td)
        # \def\ghbHTML{} tells ghb.sty this is the HTML path (skip TikZ).
        (td / "doc.tex").write_text(
            "\\def\\ghbHTML{}\n" + rewritten, encoding="utf-8")

        # latexmlpost wants the referenced graphics to exist on disk even
        # though we replace them afterwards; it reads their dimensions.
        for sig, svg in figures.items():
            shutil.copy(svg, td / f"ghbfig-{sig}.svg")

        # Any .bib alongside the source, so \cite resolves.
        for bib in page.src.parent.glob("*.bib"):
            shutil.copy(bib, td / bib.name)

        env = tex_env()
        run(["latexml", "--quiet", "--includestyles",
             f"--path={LIB}", f"--path={page.src.parent}",
             "--dest", str(td / "doc.xml"), str(td / "doc.tex")],
            cwd=td, env=env, what=f"latexml on {page.src.name}")

        # Presentation MathML is the default for html5, so it needs no flag.
        # --nodefaultresources stops LaTeXML copying its own CSS/JS next to
        # the output; the site template supplies all of that.
        cmd = ["latexmlpost", "--quiet", "--format=html5",
               "--nodefaultresources", "--novalidate",
               "--dest", str(td / "doc.html")]
        for bib in td.glob("*.bib"):
            cmd += [f"--bibliography={bib}"]
        cmd += [str(td / "doc.xml")]
        run(cmd, cwd=td, env=env, what=f"latexmlpost on {page.src.name}")

        return read(td / "doc.html")


# ---------------------------------------------------------------------------
# Stage 3: post-processing
# ---------------------------------------------------------------------------

def div_span(doc: str, start: int) -> int:
    """Index just past the </div> matching the <div> opened at `start`.

    Counting depth is the only reliable way to find a partner tag without a
    real parser, and LaTeXML nests divs freely.
    """
    i, depth = start, 1
    tag = re.compile(r"<(/?)div\b", re.IGNORECASE)
    while depth and (t := tag.search(doc, i)):
        depth += -1 if t.group(1) else 1
        i = t.end()
    return doc.find(">", i) + 1 if depth == 0 else len(doc)


def drop_div(body: str, cls: str) -> str:
    """Remove every <div class="...cls..."> block, contents included."""
    while (m := re.search(rf'<div[^>]*\bclass="[^"]*\b{cls}\b[^"]*"[^>]*>', body)):
        body = body[:m.start()] + body[div_span(body, m.end()):]
    return body


def slice_body(doc: str) -> str:
    """Pull the article content out of LaTeXML's full-page wrapper.

    Matches the opening tag of the content div then walks forward counting
    <div> depth, which is the only reliable way to find its partner without a
    real parser.
    """
    for cls in ("ltx_page_content", "ltx_page_main"):
        m = re.search(rf'<div class="{cls}"[^>]*>', doc)
        if m:
            break
    else:
        # No recognisable wrapper: fall back to whatever is inside <body>.
        m = re.search(r"<body[^>]*>(.*)</body>", doc, re.DOTALL)
        if m:
            return m.group(1)
        raise BuildError("could not locate content in LaTeXML output")

    i, depth = m.end(), 1
    tag = re.compile(r"<(/?)div\b", re.IGNORECASE)
    while depth and (t := tag.search(doc, i)):
        depth += -1 if t.group(1) else 1
        i = t.end()
    end = doc.rfind("</div>", 0, i + 6)
    body = doc[m.end():end]

    # LaTeXML's own navigation and page furniture add nothing here.
    body = re.sub(r'<div class="ltx_page_navbar".*?</div>\s*', "", body,
                  flags=re.DOTALL)
    return body.strip()


def namespace_svg_ids(svg: str, prefix: str) -> str:
    """Rewrite ids inside one SVG so several can share a page.

    dvisvgm names glyph paths g0-1, g0-2, ... per file. Inline two figures
    without this and the second one's <use> references resolve to the first
    one's glyphs, which silently renders the wrong letters.
    """
    ids = set(re.findall(r'\bid=[\'"]([^\'"]+)[\'"]', svg))
    for i in sorted(ids, key=len, reverse=True):
        new = f"{prefix}-{i}"
        svg = re.sub(rf'\bid=([\'"]){re.escape(i)}\1', rf'id=\1{new}\1', svg)
        svg = re.sub(rf'(href=[\'"])#{re.escape(i)}([\'"])',
                     rf'\g<1>#{new}\2', svg)
        svg = re.sub(rf'url\(#{re.escape(i)}\)', f'url(#{new})', svg)
    return svg


# LaTeXML represents a graphic as <img> for raster formats but as <object>
# for SVG, so both spellings have to be recognised.
FIGREF_RE = re.compile(
    r"""<img\b[^>]*\bsrc=['"](?:\./)?ghbfig-(?P<imgsig>[0-9a-f]+)\.svg['"][^>]*/?>"""
    r"""|"""
    r"""<object\b[^>]*\bdata=['"](?:\./)?ghbfig-(?P<objsig>[0-9a-f]+)\.svg['"]"""
    r"""[^>]*>\s*</object>""",
    re.IGNORECASE,
)


def inline_figures(body: str, figures: dict) -> str:
    """Swap each figure reference for the SVG itself."""
    def sub(m):
        sig = m.group("imgsig") or m.group("objsig")
        svg = read(figures[sig])
        # Strip the XML prolog and any doctype; they are invalid inline.
        svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg)
        svg = re.sub(r"<!DOCTYPE[^>]*>\s*", "", svg, flags=re.IGNORECASE)
        svg = namespace_svg_ids(svg, f"f{sig}")

        # dvisvgm sizes the SVG in TeX points against a 10pt document. Left as
        # absolute pt the diagram renders tiny next to ~19px body text, and
        # stripped entirely it stretches to the full column. Converting to em
        # against the 10pt base makes a figure scale with the surrounding text
        # exactly as it would in the PDF, and keeps it responsive.
        wm = re.search(r"<svg\b[^>]*?\bwidth=['\"]([\d.]+)pt['\"]", svg)
        style = f"width:{float(wm.group(1)) / TEX_PT_PER_EM:.3f}em" if wm else ""
        svg = re.sub(r"^(<svg\b[^>]*?)\s+width=['\"][^'\"]*['\"]", r"\1", svg)
        svg = re.sub(r"^(<svg\b[^>]*?)\s+height=['\"][^'\"]*['\"]", r"\1", svg)
        svg = svg.replace(
            "<svg ",
            f'<svg class="ghb-tikz" role="img" focusable="false" '
            f'style="{style}" ', 1)
        return f'<span class="ghb-figure">{svg}</span>'

    body = FIGREF_RE.sub(sub, body)

    # LaTeXML sometimes keeps the graphic as an <object> or a bare reference
    # when it cannot measure it; catch that spelling too.
    leftover = re.findall(r"ghbfig-([0-9a-f]+)\.svg", body)
    if leftover:
        raise BuildError(
            "figure placeholders survived post-processing: "
            + ", ".join(sorted(set(leftover)))
            + " -- LaTeXML emitted an unexpected element for the graphic"
        )
    return body


def normalize_headings(body: str) -> str:
    """Make the heading outline valid.

    LaTeXML emits an <h1> for the document title and <h2> for sections, so the
    section levels are already right once the title is removed -- the template
    renders that itself. What needs fixing is the <h6> it uses for run-in
    labels: jumping h2 -> h6 for every theorem is a malformed outline.

    Theorem and proof labels become spans, since they are run-in labels rather
    than document structure. The abstract's label becomes an h2, because that
    one really is a region heading.
    """
    # The template renders the title, date and byline itself, so LaTeXML's
    # own title block is redundant -- left in, the date shows up twice.
    body = re.sub(r'<h1 class="ltx_title ltx_title_document".*?</h1>\s*', "",
                  body, flags=re.DOTALL)
    for cls in ("ltx_dates", "ltx_authors", "ltx_creator"):
        body = drop_div(body, cls)

    def retag(cls: str, tag: str, text: str) -> str:
        return re.sub(
            rf'<h6([^>]*\bclass="[^"]*{cls}[^"]*"[^>]*)>(.*?)</h6>',
            rf"<{tag}\1>\2</{tag}>", text, flags=re.DOTALL)

    body = retag("ltx_title_theorem", "span", body)
    body = retag("ltx_title_proof", "span", body)
    body = retag("ltx_title_abstract", "h2", body)
    return body


# ---------------------------------------------------------------------------
# Templating
# ---------------------------------------------------------------------------

def render_template(name: str, **ctx) -> str:
    """Fill a template. Placeholders are {{ key }}; values are pre-escaped."""
    tpl = read(BUILD / "templates" / name)
    def sub(m):
        key = m.group(1).strip()
        if key not in ctx:
            raise BuildError(f"{name}: no value for {{{{ {key} }}}}")
        return str(ctx[key])
    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", sub, tpl)


def nav_html(current: str) -> str:
    out = []
    for href, label in NAV:
        cur = ' aria-current="page"' if href == current else ""
        out.append(f'<a href="{href}"{cur}>{html.escape(label)}</a>')
    return "\n        ".join(out)


def fmt_date(d: date | None) -> str:
    return d.strftime("%-d %B %Y") if d else ""


def write_page(page: Page, body: str):
    dest = OUT if page.slug == "index" else OUT / page.slug
    dest.mkdir(parents=True, exist_ok=True)

    meta = ""
    if page.kind == "post" and page.date:
        meta = (f'<time datetime="{page.date.isoformat()}">'
                f'{fmt_date(page.date)}</time>')

    plain_title = strip_tex(page.title)
    doc = render_template(
        "page.html",
        title=html.escape(plain_title),
        site_title=html.escape(SITE["title"]),
        description=html.escape(strip_tex(page.summary) or SITE["description"]),
        canonical=SITE["url"] + page.url,
        nav=nav_html(page.url),
        page_title=html.escape(plain_title),
        page_meta=meta,
        content=body,
        year=str(date.today().year),
    )
    (dest / "index.html").write_text(doc, encoding="utf-8")
    page.out_dir = dest


def build_posts_index(posts: list[Page]):
    """The posts listing. Generated, so publishing is just adding a .tex."""
    rows = []
    for p in posts:
        summary = (f'<p class="post-summary">{html.escape(strip_tex(p.summary))}</p>'
                   if p.summary else "")
        rows.append(
            f'      <li class="post-item">\n'
            f'        <a class="post-link" href="{p.url}">\n'
            f'          <time datetime="{p.date.isoformat()}">{fmt_date(p.date)}</time>\n'
            f'          <span class="post-title">{html.escape(strip_tex(p.title))}</span>\n'
            f'        </a>\n{summary}\n'
            f'      </li>'
        )
    listing = ("<ul class=\"post-list\">\n" + "\n".join(rows) + "\n    </ul>"
               if rows else '<p class="empty">No posts yet.</p>')

    doc = render_template(
        "page.html",
        title="Posts", site_title=html.escape(SITE["title"]),
        description="Writing, mostly about graphs and algorithms.",
        canonical=SITE["url"] + "/posts/",
        nav=nav_html("/posts/"),
        page_title="Posts", page_meta="",
        content=listing, year=str(date.today().year),
    )
    (OUT / "posts").mkdir(parents=True, exist_ok=True)
    (OUT / "posts" / "index.html").write_text(doc, encoding="utf-8")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def discover() -> list[Page]:
    pages = []
    for tex in sorted(CONTENT.glob("*.tex")):
        pages.append(Page(src=tex, slug=tex.stem, kind="page"))
    for tex in sorted(CONTENT.glob("posts/*.tex")):
        slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", tex.stem)
        pages.append(Page(src=tex, slug=f"posts/{slug}", kind="post"))
    return pages


def build(verbose=False, drafts=False) -> int:
    if not CONTENT.exists():
        raise BuildError(f"no content directory at {CONTENT}")

    pages = [load_metadata(p) for p in discover()]
    live = pages if drafts else [p for p in pages if not p.draft]
    skipped = len(pages) - len(live)

    OUT.mkdir(parents=True, exist_ok=True)
    for p in live:
        print(f"  {p.src.relative_to(ROOT)}")
        src = read(p.src)
        rewritten, figures = extract_figures(src, verbose)
        if figures:
            print(f"      {len(figures)} figure(s)")
        raw = convert(p, rewritten, figures, verbose)
        body = normalize_headings(inline_figures(slice_body(raw), figures))
        write_page(p, body)

    posts = sorted([p for p in live if p.kind == "post"],
                   key=lambda p: p.date, reverse=True)
    build_posts_index(posts)

    shutil.copytree(ASSETS, OUT / "assets", dirs_exist_ok=True)
    (OUT / ".nojekyll").write_text("")   # stop Pages running Jekyll over it
    write_sitemap(live)

    print(f"\n  {len(live)} page(s), {len(posts)} post(s)"
          + (f", {skipped} draft(s) skipped" if skipped else ""))
    return 0


def write_sitemap(pages: list[Page]):
    urls = ["/", "/posts/"] + [p.url for p in pages if p.slug != "index"]
    body = "\n".join(
        f"  <url><loc>{SITE['url']}{u}</loc></url>" for u in sorted(set(urls))
    )
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n</urlset>\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clean", action="store_true",
                    help="delete _site/ and the figure cache first")
    ap.add_argument("--serve", action="store_true",
                    help="serve _site/ on localhost:8000 after building")
    ap.add_argument("--drafts", action="store_true",
                    help="include \\draft pages, for checking them locally")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.clean:
        shutil.rmtree(OUT, ignore_errors=True)
        shutil.rmtree(CACHE, ignore_errors=True)
        print("cleaned")

    try:
        rc = build(args.verbose, args.drafts)
    except BuildError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 1

    if args.serve:
        import http.server, socketserver, functools
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(OUT))
        with socketserver.TCPServer(("", 8000), handler) as httpd:
            print("serving http://localhost:8000  (ctrl-c to stop)")
            httpd.serve_forever()
    return rc


if __name__ == "__main__":
    sys.exit(main())
