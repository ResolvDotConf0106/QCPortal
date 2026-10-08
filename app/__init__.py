import os
from flask import Flask
from app.config import Config
from app.db import init_db, close_db
from app.routes.main import main_bp

def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    # Initialize database & tables
    init_db(app)
    app.teardown_appcontext(close_db)

    # Register blueprints
    app.register_blueprint(main_bp)

    return app
