# Manuscript

The paper is a two-column LaTeX article. Its numerical claims and figures are
drawn from the tracked result tables under `outputs/ocular-code-confirmatory/`
and `outputs/ocular-code-external95/`.

Regenerate the manuscript figures from the repository root:

```text
python scripts/make_paper_figures.py
```

From this directory, compile with a standard LaTeX installation:

```text
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

The generated PDF and PNG figures are tracked under `paper/figures/`. No raw
or untracked physiological data are needed to regenerate the figure suite or
compile the paper.
