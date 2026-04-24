FROM gnzsnz/ib-gateway:10.37.1q

USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        # IB Gateway 10.45.x starts a JavaFX thread that now requires GTK runtime libs.
        libcanberra-gtk3-module \
        libglib2.0-0 \
        libgtk-3-0 \
        libxtst6 \
        python3-pip \
        xdotool && \
    pip3 install pyotp ib_insync --break-system-packages && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Give IBC more time to detect the login/config dialog on the current headless
# GCE target. The upstream 60s default has been too short during keepalive
# recovery and caused intermittent exit code 1112 before the Gateway became
# API-ready.
RUN sed -i 's/^LoginDialogDisplayTimeout=60$/LoginDialogDisplayTimeout=180/' \
    /home/ibgateway/ibc/config.ini \
    /home/ibgateway/ibc/config.ini.tmpl

COPY --chown=1000:1000 ./container_overrides/run.sh /home/ibgateway/scripts/run.sh
RUN chmod a+x /home/ibgateway/scripts/run.sh

USER ibgateway
