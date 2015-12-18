#!/bin/bash

NVM_URL="https://raw.githubusercontent.com/creationix/nvm/v0.29.0/install.sh"
NVM_DIR="$HOME/.nvm"
NVM_SCRIPT="$NVM_DIR/nvm.sh"
NODE_VERSION="5.0"
NODE_FILE="rtc.js"

if [ ! -f "$NVM_SCRIPT" ]; then
    echo "Installing nvm..."
    wget -qO- "$NVM_URL" | bash
    RC=$?
    [[ $RC != 0 ]] && exit 10
fi

source $NVM_SCRIPT

CURRENT_VERSION="`nvm current`"
if [ -z "$CURRENT_VERSION" -o "$CURRENT_VERSION" = "none" ]; then
    echo "Installing node $NODE_VERSION.."
    nvm install $NODE_VERSION
    RC=$?
    [[ $RC != 0 ]] && exit 10
fi

echo "Running npm install..."
npm install
RC=$?
[[ $RC != 0 ]] && exit 10

echo "Starting $NODE_FILE"
node $NODE_FILE
exit $?
