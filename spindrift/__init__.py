import sqlite3

from flask import Flask, render_template, request

from spindrift import db


def create_app(database_path):
    """Construct an app against a specific database.

    Taking the path as an argument rather than defining a module-level app is what lets
    every test run against its own isolated database.
    """
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = str(database_path)

    db.migrate(app.config["DATABASE_PATH"])
    app.teardown_appcontext(db.close_connection)

    @app.get("/")
    def page():
        return render_template("page.html", games=all_games())

    @app.post("/games")
    def add_game():
        name = request.form["name"].strip()
        if not name:
            return render_template("_catalogue.html", games=all_games())

        connection = db.get_connection()
        try:
            connection.execute("INSERT INTO games (name) VALUES (?)", (name,))
        except sqlite3.IntegrityError:
            error = f"{name} is already in the catalogue."
            return render_template("_catalogue.html", games=all_games(), error=error)
        connection.commit()
        return render_template("_catalogue.html", games=all_games())

    def all_games():
        return (
            db.get_connection()
            .execute("SELECT id, name FROM games ORDER BY name COLLATE NOCASE")
            .fetchall()
        )

    return app
