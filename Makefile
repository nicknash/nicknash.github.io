.PHONY: dev build serve drafts clean fonts deps pdf help

help:
	@echo "make dev     - live preview on http://localhost:8000, rebuilds as you edit"
	@echo "make build   - build the site into _site/"
	@echo "make serve   - build, then serve once (no watching)"
	@echo "make drafts  - as serve, but including \\draft pages"
	@echo "make clean   - remove _site/ and the figure cache"
	@echo "make fonts   - regenerate assets/fonts from TeX Live's STIX Two"
	@echo "make deps    - install the system packages the build needs"
	@echo "make pdf F=content/posts/x.tex - compile one page to PDF"

dev:
	python3 build/dev.py

build:
	python3 build/build.py

serve:
	python3 build/build.py --serve

drafts:
	python3 build/build.py --drafts --serve

clean:
	python3 build/build.py --clean --help >/dev/null 2>&1 || true
	rm -rf _site .cache

fonts:
	bash build/make-fonts.sh

deps:
	sudo apt-get update -qq
	sudo apt-get install -y --no-install-recommends \
	  latexml dvisvgm texlive-latex-base texlive-latex-recommended \
	  texlive-latex-extra texlive-pictures texlive-luatex \
	  texlive-science texlive-fonts-recommended

# The same source that builds a web page also compiles to a PDF, which is a
# handy way to check a page looks right before pushing.
pdf:
	@test -n "$(F)" || { echo "usage: make pdf F=content/posts/thing.tex"; exit 1; }
	TEXINPUTS=lib:content: latexmk -pdf -lualatex -outdir=_pdf $(F)
