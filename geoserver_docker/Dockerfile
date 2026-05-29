FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    GEOSERVER_VERSION=2.28.2 \
    GEOSERVER_HOME=/opt/geoserver \
    GEOSERVER_DATA_DIR=/opt/geoserver_data \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    PATH=/opt/geoserver/bin:/usr/lib/jvm/java-17-openjdk-amd64/bin:$PATH

WORKDIR /opt

RUN set -eux; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i \
            -e 's|http://archive.ubuntu.com/ubuntu|http://mirrors.ustc.edu.cn/ubuntu|g' \
            -e 's|http://security.ubuntu.com/ubuntu|http://mirrors.ustc.edu.cn/ubuntu|g' \
            -e 's|http://ports.ubuntu.com/ubuntu-ports|http://mirrors.ustc.edu.cn/ubuntu-ports|g' \
            /etc/apt/sources.list; \
    fi; \
    if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then \
        sed -i \
            -e 's|http://archive.ubuntu.com/ubuntu|http://mirrors.ustc.edu.cn/ubuntu|g' \
            -e 's|http://security.ubuntu.com/ubuntu|http://mirrors.ustc.edu.cn/ubuntu|g' \
            -e 's|http://ports.ubuntu.com/ubuntu-ports|http://mirrors.ustc.edu.cn/ubuntu-ports|g' \
            /etc/apt/sources.list.d/ubuntu.sources; \
    fi

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        openjdk-17-jre-headless \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    echo "Downloading GeoServer binary distribution..."; \
    curl -v -fL --retry 5 --retry-delay 3 --connect-timeout 20 \
        -o /tmp/geoserver-bin.zip \
        "https://downloads.sourceforge.net/project/geoserver/GeoServer/${GEOSERVER_VERSION}/geoserver-${GEOSERVER_VERSION}-bin.zip"; \
    ls -lh /tmp/geoserver-bin.zip; \
    unzip -t /tmp/geoserver-bin.zip; \
    mkdir -p /opt/geoserver; \
    unzip /tmp/geoserver-bin.zip -d /opt/geoserver; \
    rm /tmp/geoserver-bin.zip

RUN set -eux; \
    echo "Downloading GeoServer vectortiles extension..."; \
    curl -v -fL --retry 5 --retry-delay 3 --connect-timeout 20 \
        -o /tmp/vectortiles.zip \
        "https://downloads.sourceforge.net/project/geoserver/GeoServer/${GEOSERVER_VERSION}/extensions/geoserver-${GEOSERVER_VERSION}-vectortiles-plugin.zip"; \
    ls -lh /tmp/vectortiles.zip; \
    unzip -t /tmp/vectortiles.zip; \
    unzip -o /tmp/vectortiles.zip -d /opt/geoserver/webapps/geoserver/WEB-INF/lib/; \
    rm /tmp/vectortiles.zip

COPY entrypoint.sh /usr/local/bin/geoserver-entrypoint.sh
RUN chmod +x /usr/local/bin/geoserver-entrypoint.sh

VOLUME ["/opt/geoserver_data"]
EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/geoserver-entrypoint.sh"]
