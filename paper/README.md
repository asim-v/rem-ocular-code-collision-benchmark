# Manuscript

The paper is a two-column LaTeX article. Its numerical claims are drawn from
the tracked result tables under `outputs/ocular-code-confirmatory/` and
`outputs/ocular-code-external95/`.

From this directory, compile with a standard LaTeX installation:

```text
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

The figure is read directly from the tracked confirmatory output, so no
untracked physiological data are needed to compile the paper.
