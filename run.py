from app import create_app
from app.config import config

app = create_app()

if __name__ == "__main__":
    app.run(debug=config.DEBUG, use_reloader=False)
