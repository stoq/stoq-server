#!/bin/bash

# check if the build was triggered by a release commit merge
if [ $GERRIT_EVENT_TYPE = "change-merged" ]; then
  git checkout "$GERRIT_BRANCH"
  VERSION_LINE=$(git show debian/changelog|grep "^+stoq-server (") || true
  if [ -n "$VERSION_LINE" ]; then
    VERSION=$(echo $VERSION_LINE|sed "s/.*(\(.*\)).*/\1/g")
    VERSION_CHANGED=true
    echo "Plugin version changed to $VERSION"
  else
    echo "This merge dont change the version."
    exit 0
  fi
fi


# create new git tag
if [[ ($VERSION_CHANGED = true) ]]; then
  TAG_NAME=$(echo $VERSION|sed "s/~/-/g")
  if `git tag -a "$TAG_NAME" -m "New release"`;then
    echo 'new tag created'
    git push origin --tags
  else
    echo "error creating tag, aborting deb creation"
    exit 1
  fi
fi


# this can also be triggered manually to generate an alpha deb
if [ -z "$GERRIT_EVENT_TYPE" ]; then
  echo "This is a manual build."
  MANUAL_BUILD=true
  VERSION=$(head -n1 debian/changelog|sed "s/.*(\(.*\)).*/\1/g")
  GIT_HASH=`git log --pretty=format:'%h' -n 1`
  SEMVER_PATTERN="\\([^\\.]*\\)\\.\\([^\\.]*\\)\\.\\([^~]*\\)\\(.*\\)"
  MAJOR_PART=$(echo $VERSION|sed "s/$SEMVER_PATTERN/\1/g")
  MINOR_PART=$(echo $VERSION|sed "s/$SEMVER_PATTERN/\2/g")
  PATCH_PART=$(echo $VERSION|sed "s/$SEMVER_PATTERN/\3/g")
  ALPHA_VERSION="$MAJOR_PART.$((MINOR_PART + 1)).$PATCH_PART~alpha+$GIT_HASH"
  ./create-release.sh $ALPHA_VERSION
fi

# create new deb
if [[ ($VERSION_CHANGED = true || $MANUAL_BUILD = true) ]]; then
  make deb
  git checkout .
else
  echo "Version didn't change, no need for making a deb."
  exit 0
fi

