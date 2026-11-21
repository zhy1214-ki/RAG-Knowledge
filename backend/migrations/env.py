from pathlib import Path
from alembic import context
from app.core.config import Settings
from app.core.db import make_database
from app.models import Base

cfg = context.config.attributes.get("settings") or Settings()
url = cfg.database_url.get_secret_value()
if url.startswith("sqlite:///"):
    Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

if context.is_offline_mode():
    context.configure(url=url, target_metadata=context.config.attributes.get("target_metadata", Base.metadata), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine, _ = make_database(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=context.config.attributes.get("target_metadata", Base.metadata))
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
