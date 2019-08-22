FROM ubuntu:16.04

RUN apt update && \
    DEBIAN_FRONTEND="noninteractive" apt install -y software-properties-common && \
    apt-add-repository -y ppa:stoq-dev/lancamentos && \
    apt update && \
    DEBIAN_FRONTEND="noninteractive" apt install -y \
        build-essential python3.5-dev python-virtualenv \
        python3-zope.interface python3-kiwi python3-psycopg2 python3-stoqdrivers \
        python-imaging python3-pil python3-reportlab postgresql-client python3-dateutil \
        python3-mako python3-lxml python3-xlwt python3-nss python3-storm python3-weasyprint python3-requests python3-openssl \
        python3-pyinotify python3-viivakoodi python3-pykcs11 python3-tz python3-raven python3-aptdaemon.gtk3widgets \
        gir1.2-gudev-1.0 gir1.2-poppler-0.18 gir1.2-webkit-3.0 librsvg2-common iso-codes libxss1 ntp libnss3-tools libusb-1.0-0 \
        stoq stoq-server && \
    # stoq  && \ # `locale.setlocale(locale.LC_ALL, '')` explodes ...
    apt remove stoq -y && \
    locale-gen pt_BR.UTF-8 && \
    locale-gen en_US.UTF-8 && \
    apt-get -y clean && \
    rm -rf /var/lib/apt/lists/*
