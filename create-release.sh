#!/bin/bash

if [ $# -eq 0 ]
  then
    echo "No arguments supplied, expected 'major', 'minor' or 'patch'"
    exit 0
fi

version=$1
new_version=`bump2version --list --dry-run --allow-dirty $version | tail -n 1 | cut -d'=' -f 2`

dch -v $new_version "Release $new_version"
sed -i s/UNRELEASED/xenial/ debian/changelog

git add debian/changelog
git commit --amend --no-edit
bump2version $1

