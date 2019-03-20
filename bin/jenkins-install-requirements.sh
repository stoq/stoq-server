#!/bin/bash
pip install -U pip || true
pip install -U gnureadline || true
for proj in stoq kiwi stoqdrivers; do
    cd $proj
    pip install -r requirements.txt || true
    cd -
done
cd $GERRIT_PROJECT
pip install -r requirements.txt || true

# There is something wrong after installing requirements for stoq-server above, that it breaks setuptools. Se need to reinstall it to fix.
pip uninstall setuptools --yes
pip install -U setuptools
cd -
