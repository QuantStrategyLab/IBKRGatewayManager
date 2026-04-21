FROM gnzsnz/ib-gateway:latest

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

USER ibgateway
