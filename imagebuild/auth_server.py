#!/usr/bin/env python3
"""
Simple cookie-based authentication server for SongSeeker.
Validates credentials against htpasswd file and issues session cookies.
"""

import hashlib
import hmac
import os
import secrets
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import bcrypt

# Configuration
HTPASSWD_FILE = os.environ.get("HTPASSWD_FILE", "/etc/nginx/.htpasswd")
COOKIE_SECRET_FILE = os.environ.get("COOKIE_SECRET_FILE", "/etc/nginx/.cookie_secret")
COOKIE_NAME = "songseeker_auth"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
PORT = 8081


def load_cookie_secret():
    """Load cookie secret from file, or generate one if not present."""
    try:
        with open(COOKIE_SECRET_FILE, "r") as f:
            secret = f.read().strip()
            if secret:
                return secret
    except FileNotFoundError:
        pass
    # Fallback to a generated secret (not persistent across restarts)
    print(f"Warning: {COOKIE_SECRET_FILE} not found, using generated secret")
    return secrets.token_hex(32)


COOKIE_SECRET = load_cookie_secret()


def load_htpasswd():
    """Load users from htpasswd file."""
    users = {}
    try:
        with open(HTPASSWD_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if ":" in line:
                    username, password_hash = line.split(":", 1)
                    users[username] = password_hash
    except FileNotFoundError:
        print(f"Warning: {HTPASSWD_FILE} not found")
    return users


def verify_password(users, username, password):
    """Verify password against htpasswd hash (bcrypt format)."""
    if not users or username not in users:
        return False
    stored_hash = users[username]
    # Handle bcrypt hashes ($2y$ or $2a$ or $2b$)
    if stored_hash.startswith("$2"):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except Exception as e:
            print(f"bcrypt error: {e}")
            return False
    return False


def create_session_token(username):
    """Create a signed session token."""
    timestamp = str(int(time.time()))
    data = f"{username}:{timestamp}"
    signature = hmac.new(COOKIE_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}:{signature}"


def verify_session_token(token):
    """Verify a session token is valid and not expired."""
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        username, timestamp, signature = parts

        # Verify signature
        data = f"{username}:{timestamp}"
        expected_sig = hmac.new(COOKIE_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return False

        # Check expiration
        token_time = int(timestamp)
        if time.time() - token_time > COOKIE_MAX_AGE:
            return False

        return True
    except (ValueError, TypeError):
        return False


class AuthHandler(BaseHTTPRequestHandler):
    users = None

    def log_message(self, format, *args):
        """Log requests for debugging."""
        print(f"[AUTH] {self.command} {self.path} - {args[1] if len(args) > 1 else ''}")

    def send_cors_headers(self):
        """Send CORS headers for local development."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        """Handle preflight requests."""
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        """Handle auth verification requests."""
        path = urlparse(self.path).path

        if path == "/auth/verify":
            # Check for valid session cookie
            cookies = self.parse_cookies()
            token = cookies.get(COOKIE_NAME)

            if token and verify_session_token(token):
                self.send_response(200)
                self.end_headers()
            else:
                self.send_response(401)
                self.end_headers()

        elif path == "/auth/logout":
            # Clear the cookie
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Set-Cookie", f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")
            self.end_headers()
            self.wfile.write(b"Logged out")

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        """Handle login requests."""
        path = urlparse(self.path).path
        print(f"[AUTH] POST received - raw path: {self.path}, parsed path: {path}")

        if path == "/auth/login":
            # Parse form data
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            params = parse_qs(body)

            username = params.get("username", [""])[0]
            password = params.get("password", [""])[0]

            # Load users if not cached
            if AuthHandler.users is None:
                AuthHandler.users = load_htpasswd()

            # Verify credentials
            if verify_password(AuthHandler.users, username, password):
                # Create session token
                token = create_session_token(username)

                # Send success response with cookie
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie",
                    f"{COOKIE_NAME}={token}; Path=/; Max-Age={COOKIE_MAX_AGE}; HttpOnly; SameSite=Strict")
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            else:
                # Invalid credentials
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"success": false, "error": "Invalid credentials"}')
        else:
            self.send_response(404)
            self.end_headers()

    def parse_cookies(self):
        """Parse cookies from request headers."""
        cookies = {}
        cookie_header = self.headers.get("Cookie", "")
        for item in cookie_header.split(";"):
            item = item.strip()
            if "=" in item:
                name, value = item.split("=", 1)
                cookies[name.strip()] = value.strip()
        return cookies


def main():
    print(f"Starting auth server on port {PORT}")
    server = HTTPServer(("127.0.0.1", PORT), AuthHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
