# Stage 1: Clone plex-lists repo
FROM alpine/git AS plex-lists
ARG PLEX_LISTS_REPO=https://github.com/abarthen/songseeker-plex-lists.git
ARG PLEX_LISTS_BRANCH=main
RUN git clone --depth 1 --branch ${PLEX_LISTS_BRANCH} ${PLEX_LISTS_REPO} /plex-lists

# Stage 2: Final image
FROM nginx

# Install Python for auth server and htpasswd tools
RUN apt-get update && apt-get install -y python3 python3-pip apache2-utils && rm -rf /var/lib/apt/lists/*

# Install bcrypt for htpasswd authentication
RUN pip3 install --break-system-packages bcrypt

# Copy nginx config
COPY imagebuild/default.conf /etc/nginx/conf.d/default.conf

# Copy auth server
COPY imagebuild/auth_server.py /opt/auth_server.py
COPY imagebuild/start.sh /opt/start.sh
RUN chmod +x /opt/start.sh

# Copy web files
RUN rm -rf /usr/share/nginx/html/*
COPY *.js *.html *.css *.png manifest.json /usr/share/nginx/html/
COPY icons/* /usr/share/nginx/html/icons/
# Copy favicon to root for browser default requests
COPY icons/favicon.ico /usr/share/nginx/html/favicon.ico

# Copy mapping files from plex-lists repo to staging directory
# start.sh will copy these to /plex-data/ at runtime if not already present
RUN mkdir -p /opt/plex-defaults
COPY --from=plex-lists /plex-lists/plex-manifest.json /opt/plex-defaults/
COPY --from=plex-lists /plex-lists/plex-mapping-*.json /opt/plex-defaults/

# Create plex-data directory (may be overlaid by volume mount)
RUN mkdir -p /plex-data

# Create empty htpasswd file (will be overwritten by mount)
RUN touch /etc/nginx/.htpasswd

# Use custom start script to run both nginx and auth server
CMD ["/opt/start.sh"]
