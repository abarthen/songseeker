#!/bin/bash

# Copy default plex mapping files if not already present in /plex-data/
for file in /opt/plex-defaults/*.json; do
    filename=$(basename "$file")
    if [ ! -f "/plex-data/$filename" ]; then
        echo "Copying default $filename to /plex-data/"
        cp "$file" "/plex-data/$filename"
    fi
done

# Start the auth server in the background
python3 /opt/auth_server.py &

# Start nginx in the foreground
nginx -g "daemon off;"
