codebraid pandoc -f markdown -t html --overwrite --standalone --embed-resources --css example.css -o python.html python.cbmd
codebraid pandoc -f markdown -t markdown --overwrite --standalone -o python_output.md python.cbmd
