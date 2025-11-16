from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/api/record_event", methods=["GET"])
def record_event():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
