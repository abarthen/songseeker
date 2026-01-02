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

# Note: plex-config.json, plex-manifest.json, and plex-mapping-*.json are mounted at runtime

# Create empty htpasswd file (will be overwritten by mount)
RUN touch /etc/nginx/.htpasswd

# Use custom start script to run both nginx and auth server
CMD ["/opt/start.sh"]
