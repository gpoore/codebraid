codebraid pandoc -f markdown -t html --overwrite --standalone --embed-resources --css example.css -o julia.html julia.cbmd
codebraid pandoc -f markdown -t markdown --overwrite --standalone -o julia_output.md julia.cbmd
