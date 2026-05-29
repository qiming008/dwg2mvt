#!/bin/sh
set -eu

GEOSERVER_HOME="${GEOSERVER_HOME:-/opt/geoserver}"
GEOSERVER_DATA_DIR="${GEOSERVER_DATA_DIR:-/opt/geoserver_data}"
export GEOSERVER_HOME GEOSERVER_DATA_DIR

mkdir -p "$GEOSERVER_DATA_DIR"

# Seed the persistent data directory the first time the container starts.
if [ -z "$(find "$GEOSERVER_DATA_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
    if [ -d "$GEOSERVER_HOME/data_dir" ]; then
        cp -a "$GEOSERVER_HOME/data_dir/." "$GEOSERVER_DATA_DIR/"
    fi
fi

JAVA_BIN="$(command -v java || true)"

if [ -z "$JAVA_BIN" ]; then
    echo "A Java runtime was not found on PATH."
    exit 1
fi

if [ -z "${JAVA_OPTS:-}" ]; then
    JAVA_OPTS="-Xms128m -Xmx512m -XX:+UseSerialGC -XX:ActiveProcessorCount=1 -XX:ParallelGCThreads=1 -XX:ConcGCThreads=1 -XX:CICompilerCount=2"
fi

exec "$JAVA_BIN" \
    ${JAVA_OPTS} \
    --add-exports=java.desktop/sun.awt.image=ALL-UNNAMED \
    --add-opens=java.base/java.lang=ALL-UNNAMED \
    --add-opens=java.base/java.util=ALL-UNNAMED \
    --add-opens=java.base/java.lang.reflect=ALL-UNNAMED \
    --add-opens=java.base/java.text=ALL-UNNAMED \
    --add-opens=java.desktop/java.awt.font=ALL-UNNAMED \
    --add-opens=java.desktop/sun.awt.image=ALL-UNNAMED \
    --add-opens=java.naming/com.sun.jndi.ldap=ALL-UNNAMED \
    --add-opens=java.desktop/sun.java2d.pipe=ALL-UNNAMED \
    -Djetty.base="$GEOSERVER_HOME" \
    -DGEOSERVER_DATA_DIR="$GEOSERVER_DATA_DIR" \
    -Djava.awt.headless=true \
    -DSTOP.PORT=8079 \
    -DSTOP.KEY=geoserver \
    -jar "$GEOSERVER_HOME/start.jar" \
    ${JETTY_OPTS:-}
