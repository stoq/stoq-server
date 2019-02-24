#!/bin/bash

version=$1
tuple_version=`echo $version | sed "s/\./, /g" | sed "s/~\([^,]*\)/, \"\1\"/g"`

dch -v $1 "Release $version"
sed -i s/UNRELEASED/xenial/ debian/changelog

sed -i "s/__version__ = .*/__version__ = ($tuple_version)/" stoqserver/__init__.py

