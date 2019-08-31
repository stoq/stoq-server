FROM ubuntu:16.04

RUN DEBIAN_FRONTEND="noninteractive" apt update -yq && \
    DEBIAN_FRONTEND="noninteractive" apt install -y software-properties-common && \
    apt-add-repository -y ppa:stoq-dev/lancamentos && \
    DEBIAN_FRONTEND="noninteractive" apt update -yq && \
    DEBIAN_FRONTEND="noninteractive" apt install -y \
        build-essential locales git postgresql-client ntp xvfb iso-codes libxss1 \
        gir1.2-gudev-1.0 gir1.2-poppler-0.18 gir1.2-webkit-3.0 librsvg2-common poppler-utils \
        libnss3-tools libnss3-dev libusb-1.0-0 libxml2-utils \
        python3.5-dev python3-zope.interface python3-kiwi python3-psycopg2 python3-pil \
        python3-reportlab python3-dateutil python3-mako python3-lxml python3-xlwt python3-nss \
        python3-storm python3-weasyprint python3-requests python3-openssl python3-pyinotify \
        python3-viivakoodi python3-pykcs11 python3-tz python3-raven python3-aptdaemon.gtk3widgets \
        python3-nose python3-mock python3-pyflakes python3-gevent python3-psutil python3-flask \
        python3-flask-restful python3-blinker python3-tzlocal python3-jwt python3-docutils \
        python3-stoqdrivers && \
    apt remove python2.7 -y && \
    apt autoremove -y && \
    locale-gen pt_BR.UTF-8 && \
    locale-gen en_US.UTF-8 && \
    apt-get -y clean && \
    rm -rf /var/lib/apt/lists/*
