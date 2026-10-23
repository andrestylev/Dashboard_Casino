from sqlalchemy import create_engine

from app.config import settings

# The engine connects lazily, so importing this module never needs a running database.
engine = create_engine(settings.database_url, pool_pre_ping=True)
