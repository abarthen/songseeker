FROM nginx

# Install Python for auth server and htpasswd tools
RUN apt-get update && apt-get install -y python3 apache2-utils && rm -rf /var/lib/apt/lists/*

# Copy nginx config
COPY imagebuild/default.conf /etc/nginx/conf.d/default.conf

# Copy auth server
COPY imagebuild/auth_server.py /opt/auth_server.py
COPY imagebuild/start.sh /opt/start.sh
RUN chmod +x /opt/start.sh

# Copy web files
RUN rm -rf /usr/share/nginx/html/*
COPY *.js *.html *.css *.png /usr/share/nginx/html/
COPY icons/* /usr/share/nginx/html/icons/

# Note: plex-config.json is mounted at runtime, not copied during build

# Create playlists directory - mount your playlists and plex mappings here
RUN mkdir -m 755 -p /usr/share/nginx/html/playlists

# Create empty htpasswd file (will be overwritten by mount)
RUN touch /etc/nginx/.htpasswd

# Use custom start script to run both nginx and auth server
CMD ["/opt/start.sh"]
