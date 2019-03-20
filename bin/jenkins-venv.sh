#!/bin/bash
VENV_NAME=venv3
VENV_ARGS="--python=/usr/bin/python3 --system-site-packages"
rm -fr "$VENV_NAME"
virtualenv $VENV_ARGS $VENV_NAME
source "$VENV_NAME/bin/activate"

