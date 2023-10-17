codebraid pandoc -f markdown -t html --overwrite --standalone --embed-resources --css example.css -o bash.html bash.cbmd
codebraid pandoc -f markdown -t markdown --overwrite --standalone -o bash_output.md bash.cbmd
