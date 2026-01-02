FROM nginx

COPY imagebuild/default.conf /etc/nginx/conf.d/default.conf

RUN rm -rf /usr/share/nginx/html/*
COPY *.js *.json *.csv *.html *.css *.png icons/* /usr/share/nginx/html/

# Create playlists directory - mount your playlists and plex mappings here
RUN mkdir -m 755 -p /usr/share/nginx/html/playlists
