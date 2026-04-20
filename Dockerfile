FROM gnzsnz/ib-gateway:latest

USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3-pip xdotool && \
    pip3 install pyotp ib_insync --break-system-packages && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

USER ibgateway
