FROM ghcr.io/osgeo/gdal:ubuntu-small-latest-amd64

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    APP_WORK_DIR=/app/backend/data \
    APP_DWG2DXF_CMD=dwg2dxf \
    APP_DWG2SVG_CMD=dwg2SVG \
    APP_ORIGINAL_PREVIEW_TIMEOUT_SECONDS=300 \
    APP_ORIGINAL_PREVIEW_TEMP_DIR=/tmp/libredwg_original_preview \
    APP_OGR2OGR_CMD=ogr2ogr

WORKDIR /app/backend

RUN set -eux; \
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do \
        if [ -f "$f" ]; then \
            sed -i \
                -e 's|http://archive.ubuntu.com/ubuntu|http://mirrors.ustc.edu.cn/ubuntu|g' \
                -e 's|http://security.ubuntu.com/ubuntu|http://mirrors.ustc.edu.cn/ubuntu|g' \
                -e 's|http://ports.ubuntu.com/ubuntu-ports|http://mirrors.ustc.edu.cn/ubuntu-ports|g' \
                "$f"; \
        fi; \
    done

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        autoconf \
        automake \
        build-essential \
        ca-certificates \
        flex \
        git \
        libpcre2-dev \
        libtool \
        libxml2-dev \
        pkg-config \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Build LibreDWG from source so the container provides dwg2dxf on Linux.
RUN set -eux; \
    tmpdir="$(mktemp -d)"; \
    cd "$tmpdir"; \
    git clone --depth 1 --branch 0.13.4 https://github.com/libredwg/libredwg.git; \
    cd libredwg; \
    git submodule update --init --recursive; \
    ./autogen.sh; \
    CFLAGS="-Wno-error" ./configure --disable-bindings --disable-docs --disable-shared || { cat config.log; exit 1; }; \
    make -j"$(nproc)" V=1 || exit 1; \
    make install; \
    ldconfig; \
    cd /; \
    rm -rf "$tmpdir"

COPY requirements.txt ./
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio", "--http", "h11"]
