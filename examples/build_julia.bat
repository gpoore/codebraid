codebraid pandoc -f markdown -t html --overwrite --standalone --self-contained --css example.css -o julia.html julia.cbmd
codebraid pandoc -f markdown -t markdown --overwrite --standalone -o julia_output.md julia.cbmd
