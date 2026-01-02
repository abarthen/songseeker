#!/bin/bash

# Start the auth server in the background
python3 /opt/auth_server.py &

# Start nginx in the foreground
nginx -g "daemon off;"
