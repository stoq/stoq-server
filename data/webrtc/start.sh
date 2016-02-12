#!/bin/bash

VERSION_FILE=".version"
NVM_URL="https://raw.githubusercontent.com/creationix/nvm/v0.30.1/install.sh"
NVM_DIR="$HOME/.nvm"
NVM_SCRIPT="$NVM_DIR/nvm.sh"
NODE_VERSION="4.3"  # LTS version
NODE_ABI="46"
NODE_FILE="rtc.js"
WRTC_VERSION="0.0.59"
RESOURCES_URL="https://s3.amazonaws.com/stoq-resources"
GLIBC_REQUIRED="GLIBCXX_3.4.19"

# Our compiled wrtc.node requires libstdc++ to have GLIBC_REQUIRED
# At the time of writing this, anything > trusty will have it.
for _FILE in `/sbin/ldconfig -p | grep stdc++ | cut -d ' ' -f 4`; do
    if strings "$_FILE" | grep "$GLIBC_REQUIRED"; then
        _FOUND="1"
        break
    fi
done
[[ "$_FOUND" != "1" ]] && exit 11

if [ ! -f "$NVM_SCRIPT" ]; then
    echo "Installing nvm..."
    wget -qO- "$NVM_URL" | bash
    RC=$?
    [[ $RC != 0 ]] && exit 10
fi

source $NVM_SCRIPT

CURRENT_VERSION="`nvm current`"
if [[ "$CURRENT_VERSION" != *"$NODE_VERSION"* ]]; then
    echo "Installing node $NODE_VERSION..."
    nvm install $NODE_VERSION
    RC=$?
    [[ $RC != 0 ]] && exit 10
    nvm use $NODE_VERSION
    RC=$?
    [[ $RC != 0 ]] && exit 10
fi

# We used to require node 5.0, but we are using 4.2 now because it is LTS.
# Because of that, we need to regenerate the node_modules dir. Before, we
# didn't have that version file and thus the lack of it means we need to remove
# it. In the future, we can use its number to know what to migrate in a better
# way for any other problem we may find.
if [ ! -f "$VERSION_FILE" ]; then
    rm -rf node_modules
    echo "1" > $VERSION_FILE
fi

echo "Running npm install..."
npm install
RC=$?
# On some rare ocasions node_modules can corrupt and npm install will fail.
# If that happens, remove it and do a 'npm install' again to fix it
if [[ $RC != 0 ]]; then
    echo "node_modules probably corrupted. Reinstalling it..."
    rm -rf node_modules
    npm install
    RC=$?
    [[ $RC != 0 ]] && exit 10
fi

[[ "`getconf LONG_BIT`" = "64" ]] && _ARCH="x64" || _ARCH="ia32"
_WRTC_DIR="node_modules/wrtc/build/wrtc"
_RELEASE_DIR="$_WRTC_DIR/v$WRTC_VERSION/Release/node-v$NODE_ABI-linux-$_ARCH"
_BINARY_FILE="$_RELEASE_DIR/wrtc.node"
if [ ! -f "$_BINARY_FILE" ]; then
    # We can only run npm install wrtc once or else it would overwrite
    # the binary file we download and we would have to download it again
    npm install wrtc@$WRTC_VERSION --ignore-scripts
    RC=$?
    [[ $RC != 0 ]] && exit 10

    mkdir -p $_RELEASE_DIR
    wget "$RESOURCES_URL/wrtc_${NODE_ABI}_${_ARCH}.node" -O $_BINARY_FILE
    RC=$?
    [[ $RC != 0 ]] && exit 10
fi

echo "Starting $NODE_FILE..."
NODE_PATH=node_modules node $NODE_FILE
exit $?
