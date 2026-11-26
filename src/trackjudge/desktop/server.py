from pathlib import Path

from bottle import Bottle, abort, static_file

STATIC = Path(__file__).parent / "static"


def application(session):
    app = Bottle()

    @app.get("/")
    def index():
        return static_file("index.html", root=STATIC, headers={"Cache-Control": "no-store"})

    @app.get("/media/<key:re:[0-9a-f]{32}>")
    def media(key):
        path = session.media(key)
        if path is None:
            abort(404)
        return static_file(
            path.name, root=path.parent, headers={"Cache-Control": "private, no-store"}
        )

    @app.get("/<asset:path>")
    def asset(asset):
        return static_file(asset, root=STATIC)

    return app
