#!/bin/bash

pyenv --version

cd "$(pyenv root)"
git status --short
git pull

cd -
pyenv install --list | grep '3\.12\.'

pyenv install 3.12.13
