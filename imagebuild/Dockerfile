FROM nginx

# Install htpasswd for generating password files
RUN apt-get update && apt-get install -y apache2-utils && rm -rf /var/lib/apt/lists/*

COPY imagebuild/default.conf /etc/nginx/conf.d/default.conf

RUN rm -rf /usr/share/nginx/html/*
COPY *.js *.json *.csv *.html *.css *.png icons/* /usr/share/nginx/html/

# Create playlists directory - mount your playlists and plex mappings here
RUN mkdir -m 755 -p /usr/share/nginx/html/playlists

# Create empty htpasswd file (will be overwritten by mount or entrypoint)
RUN touch /etc/nginx/.htpasswd
