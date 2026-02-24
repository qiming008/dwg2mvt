FROM docker.io/geoserver/geoserver:2.25.0

# Switch to root to install packages
USER root

# Install Vector Tiles Plugin
# Note: The version must match the base image exactly
RUN wget -c https://sourceforge.net/projects/geoserver/files/GeoServer/2.25.0/extensions/geoserver-2.25.0-vectortiles-plugin.zip -O /tmp/vectortiles.zip && \
    unzip /tmp/vectortiles.zip -d /opt/geoserver/webapps/geoserver/WEB-INF/lib/ && \
    rm /tmp/vectortiles.zip

# Switch back to geoserver user
USER geoserver
