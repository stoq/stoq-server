#!/bin/bash
repo forall -c "git reset --hard"
repo forall -c "git clean -fxd"
cd $GERRIT_PROJECT
git fetch --all
cd -
repo forall -c "git submodule init"
repo forall -c "git submodule update"

