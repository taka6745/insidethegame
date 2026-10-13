FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-dev python3-venv build-essential cmake git ca-certificates \
    libgl1-mesa-dev libegl1-mesa-dev libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev \
    libsdl2-gfx-dev libboost-python-dev libboost-thread-dev libboost-system-dev \
    libboost-filesystem-dev && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install pip==23.0.1 setuptools==65.5.0 wheel==0.38.4 && \
    pip install numpy==1.23.5 gym==0.21.0 pygame==2.6.1 opencv-python-headless==4.10.0.84 psutil==6.1.1 absl-py==2.1.0 six==1.17.0
WORKDIR /opt/football
RUN git clone https://github.com/google-research/football.git . && \
    git checkout 3d9e754720a95621bba6475c4d3b0d56fe919014
COPY telemetry.patch /tmp/telemetry.patch
RUN git apply /tmp/telemetry.patch && pip install --no-deps --no-build-isolation .
WORKDIR /work
ENV SDL_VIDEODRIVER=dummy
ENTRYPOINT ["python"]
