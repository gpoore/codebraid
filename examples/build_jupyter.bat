codebraid pandoc -f markdown -t html --overwrite --standalone --embed-resources --css example.css --webtex -o jupyter.html jupyter.cbmd
codebraid pandoc -f markdown -t markdown --overwrite --standalone -o jupyter_output.md jupyter.cbmd
