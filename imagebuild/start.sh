#!/bin/bash

# Copy built-in plex mapping files to /plex-data/ (always overwrite to get latest from build)
for file in /opt/plex-defaults/*.json; do
    filename=$(basename "$file")
    echo "Deploying $filename to /plex-data/"
    cp "$file" "/plex-data/$filename"
done

# Start the auth server in the background
python3 /opt/auth_server.py &

# Start nginx in the foreground
nginx -g "daemon off;"
