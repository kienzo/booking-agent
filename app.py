# app.py
from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def index():
    # This will render templates/golf_booker_ui.html
    return render_template("golf_booker_ui.html")

if __name__ == "__main__":
    app.run(debug=True)
