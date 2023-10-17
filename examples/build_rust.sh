codebraid pandoc -f markdown -t html --overwrite --standalone --embed-resources --css example.css -o rust.html rust.cbmd
codebraid pandoc -f markdown -t markdown --overwrite --standalone -o rust_output.md rust.cbmd
