# nicknash.github.io

A blog written in LaTeX. Each page is a real `.tex` document; a build step
converts it to HTML with MathML for the maths, and compiles every TikZ picture
to SVG. Published to GitHub Pages at <https://nicknash.github.io>.

## Writing a post

Add a `.tex` file under `content/posts/`, named `YYYY-MM-DD-slug.tex`:

```latex
\documentclass[11pt]{article}
\usepackage{ghb}

\title{Counting triangles by degeneracy ordering}
\date{2026-08-16}
\summary{One or two sentences for the posts index.}

\begin{document}
\section{The problem}
...
\end{document}
```

That's the whole publishing step — the posts index is generated from whatever
is in `content/posts/`, sorted by date. Push to `main` and it deploys.

Pages that aren't posts go directly in `content/` and get their own URL from
the filename — `content/about.tex` would serve at `/about/`. Add them to `NAV`
in `build/build.py` to put them in the header. `content/index.tex` is the home
page.

`content/posts/2026-08-16-example.tex` is a worked example covering theorems, a
TikZ figure, numbered equations, cross-references and a bibliography. It is
marked `\draft` so it never publishes; view it with `make drafts` or delete it
once it has served its purpose.

### Metadata

| Command | Effect |
| --- | --- |
| `\title{...}` | Page title. Used for `<title>`, the heading, and the index. |
| `\date{YYYY-MM-DD}` | Sort key for the posts index. Required on posts; a `YYYY-MM-DD-` filename prefix works too. |
| `\summary{...}` | Blurb on the posts index and the `<meta name="description">`. |
| `\draft` | Build it locally, but keep it out of the index and sitemap. |

### What you can use

`\usepackage{ghb}` provides `amsthm` environments (`theorem`, `lemma`,
`proposition`, `corollary`, `claim`, `conjecture`, `definition`, `example`,
`problem`, `remark`, `note`, plus `proof`), sharing one counter numbered by
section, and the shared math macros in `lib/ghbmath.sty`.

Citations work: put a `.bib` beside the source and use `\cite` with
`\bibliography{refs}`.

Figures are plain TikZ — just write a `tikzpicture` in the document. Anything
used inside one must be reachable from `lib/ghbtikz.sty`, because figures are
compiled in isolation.

Diagrams drawn in default black automatically follow the page's text colour, so
they work in dark mode without a second asset. Greys written as `black!30`
stay fixed, so avoid those for anything load-bearing on a dark background.

## Building

```
make deps     # one-time: TeX Live, LaTeXML, dvisvgm
make dev      # live preview: rebuilds and reloads as you edit  <- use this
make build    # build into _site/
make serve    # build and serve once, no watching
make drafts   # as serve, including \draft pages
make clean    # drop _site/ and the figure cache
```

`make dev` is the one to leave running while writing. It serves
<http://localhost:8000>, watches the sources, and reloads the browser on
change. Drafts are included so you can see a `\draft` post as you write it.

It rebuilds only what your edit affects, because LaTeXML is the slow part:
editing one `.tex` takes about 1.5s, where a full rebuild is closer to 15s.
Editing a `.sty` or the template rebuilds everything, since a macro change can
reach any page; editing CSS just copies the file and reloads, with no LaTeX at
all.

If a build fails the server keeps serving the last good version and shows the
error as a banner in the page, so a stray `\begin` doesn't leave you looking
at a blank screen.

## Publishing status

The site is currently **not published**. The repository is private, which is
what takes a `<user>.github.io` site offline — GitHub does not allow
deactivating Pages on a user site directly. The deploy workflow's `push`
trigger is commented out to match. `.github/workflows/deploy.yml` carries the
three commands needed to put it back online.

Because the source is ordinary LaTeX, any page also compiles to a PDF, which
is a quick way to check it before pushing:

```
make pdf F=content/posts/2026-08-16-counting-triangles.tex
```

## How it works

`build/build.py`, per source file:

1. **Extract figures.** Every `tikzpicture` is pulled out, compiled on its own
   with LuaLaTeX, and converted to SVG by dvisvgm. Results are cached by a hash
   of the picture *and* the style files, so editing `\tikzset` correctly
   invalidates stale figures. `dvisvgm --currentcolor` maps pure black to
   `currentColor`, which is what makes dark mode work.
2. **Rewrite.** Each picture becomes an `\includegraphics` of its SVG, and
   `\ghbHTML` is defined so `ghb.sty` skips loading TikZ — LaTeXML never has to
   deal with it.
3. **Convert.** `latexml` then `latexmlpost` produce HTML5 with MathML.
4. **Post-process.** The body is lifted out of LaTeXML's page furniture, the
   SVGs are inlined (with their internal IDs namespaced, since dvisvgm reuses
   names like `g0-1` across files), headings are shifted down a level so the
   page title is the only `h1`, and the result is wrapped in the template.

Maths is set in STIX Two Math, a full OpenType MATH font, which is why display
equations look close to a PDF rather than like browser-default MathML. The
fonts live in `assets/fonts` and are regenerated by `build/make-fonts.sh` from
the copies TeX Live already ships.

## Layout

```
content/          the site, as LaTeX
  index.tex         home page
  about.tex         → /about/
  posts/            → /posts/<slug>/
lib/              *.sty shared by every document
build/            build.py, page template, font script
assets/           CSS and web fonts
.github/workflows deploy to Pages on push to main
```
