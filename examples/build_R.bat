codebraid pandoc -f markdown -t html --overwrite --standalone --self-contained --css example.css -o R.html R.cbmd
codebraid pandoc -f markdown -t markdown --overwrite --standalone -o R_output.md R.cbmd
