codebraid pandoc -f markdown -t html --overwrite --standalone --self-contained --css example.css -o gap.html gap.cbmd
codebraid pandoc -f markdown -t markdown --overwrite --standalone -o gap_output.md gap.cbmd
