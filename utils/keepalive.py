from threading import Thread

from flask import Flask

import utils.config as config


# Instantiate Flask app
flask_app = Flask(__name__)

@flask_app.route("/", methods=["GET"])
def home() -> str:
    return "I'm alive"

def run() -> None:
    """
    Run Flask app in a daemon thread
    """
    def flask_run() -> None:
        flask_app.run(host=config.host, port=config.port)

    flask_thread = Thread(target=flask_run, daemon=True)
    flask_thread.start()