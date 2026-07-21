"""
Wire CORS + Alpaca routes into the Render trading Flask app (wicksense-backend).

Add near the top of the main app.py (after `app = Flask(__name__)`):

    from wicksense_backend.register_extensions import register_wicksense_extensions
    register_wicksense_extensions(app)

Requires env vars on Render:
  SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY
  ALPACA_CREDENTIALS_ENCRYPTION_KEY  (base64 32-byte key; NEVER a VITE_* var)
"""

from wicksense_backend.cors_config import apply_cors, register_global_options_handler
from wicksense_backend.alpaca_blueprint import alpaca_bp


def register_wicksense_extensions(app):
    apply_cors(app)
    register_global_options_handler(app)
    app.register_blueprint(alpaca_bp)
