# Linux xrdp test host. It plays the vendor-hosted machine: it only serves an RDP session
# running the synthetic application. No executor code runs here.
FROM debian:bookworm-slim
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      xrdp xorgxrdp xserver-xorg-core x11-xserver-utils dbus-x11 ssl-cert \
      python3 python3-tk fonts-dejavu-core procps \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m -s /bin/bash clerk && adduser xrdp ssl-cert \
    && printf 'allowed_users=anybody\nneeds_root_rights=no\n' > /etc/X11/Xwrapper.config \
    && mkdir -p /srv/data && chown clerk:clerk /srv/data
# Only the Xorg session, started automatically with the credentials sent by the client.
RUN sed -i 's/^\[Xvnc\]/[XvncDisabled]/; s/^#\?autorun=.*/autorun=Xorg/' /etc/xrdp/xrdp.ini \
    && sed -i '/^\[XvncDisabled\]/,/^$/d' /etc/xrdp/xrdp.ini
COPY app /srv/app
COPY startwm.sh /etc/xrdp/startwm.sh
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /etc/xrdp/startwm.sh /entrypoint.sh
EXPOSE 3389
ENTRYPOINT ["/entrypoint.sh"]
