codebraid pandoc -f markdown -t html --overwrite --standalone --embed-resources --css example.css -o javascript.html javascript.cbmd
codebraid pandoc -f markdown -t markdown --overwrite --standalone -o javascript_output.md javascript.cbmd
