import os
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask import Flask
from flask_cors import CORS
from flask_migrate import Migrate
from flask_caching import Cache
from flask_compress import Compress
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
ma = Marshmallow()
cache = Cache()
application = Flask(__name__)

# FRONTEND_ORIGINS: comma-separated list of allowed origins (set in .env)
_origins_raw = os.environ.get('FRONTEND_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000')
FRONTEND_ORIGINS = [o.strip() for o in _origins_raw.split(',') if o.strip()]
CORS(application, origins=FRONTEND_ORIGINS, supports_credentials=True)

application.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI')
application.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
application.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Each serverless invocation may run in its own container, so keep the
# per-container pool tiny — a handful of concurrent cold starts must not be
# able to exhaust Supabase's connection cap. pool_pre_ping guards against
# handing out a connection a frozen/thawed container has let go stale, and
# pool_recycle keeps connections from outliving the pooler's own timeout.
application.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 1,
    'max_overflow': 2,
    'pool_pre_ping': True,
    'pool_recycle': 280,
    'pool_timeout': 10,
    # pool_pre_ping only re-validates a connection when it's checked back
    # OUT of the pool -- it can't catch one that goes stale mid-transaction
    # during a single long-lived session (e.g. a bulk import script), which
    # was observed hanging indefinitely with the connection stuck "idle in
    # transaction" after the network silently dropped it. TCP keepalives
    # make a dead connection detectable within ~60s instead of never, and
    # statement_timeout kills any single query that hangs server-side so it
    # comes back as a catchable error instead of blocking forever.
    'connect_args': {
        'keepalives': 1,
        'keepalives_idle': 30,
        'keepalives_interval': 10,
        'keepalives_count': 3,
        'options': '-c statement_timeout=30000',
    },
}

# Cache: simple in-memory, no Redis required
application.config['CACHE_TYPE'] = 'SimpleCache'
application.config['CACHE_DEFAULT_TIMEOUT'] = 60  # seconds

# Compression: gzip all JSON/text responses automatically
application.config['COMPRESS_REGISTER'] = True
application.config['COMPRESS_MIMETYPES'] = [
    'application/json', 'text/html', 'text/css', 'application/javascript'
]

db.init_app(application)
ma.init_app(application)
cache.init_app(application)
Compress(application)
migrate = Migrate(application, db)
