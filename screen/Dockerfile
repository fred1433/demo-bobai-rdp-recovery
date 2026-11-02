# Virtual monitor for the client side. macOS has no root-free Xvfb, so the X display that the
# FreeRDP client draws into lives here, published on 127.0.0.1 only. The FreeRDP client and the
# executor run on macOS and connect to it as X clients. Openbox only draws the client's title bar.
# This isolated screen exists so the faults can be replayed automatically and recorded without
# touching the real desktop; it is not a security feature of a customer workstation.
FROM debian:bookworm-slim
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      xvfb ffmpeg x11-utils openbox \
    && rm -rf /var/lib/apt/lists/*
EXPOSE 6000
CMD ["sh", "-c", "Xvfb :0 -screen 0 1280x860x24 -listen tcp -ac +extension XTEST & sleep 1; DISPLAY=:0 exec openbox"]
