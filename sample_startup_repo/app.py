"""CampusEats web API: students order food from campus canteens."""
from flask import Flask, jsonify, request

import config
from orders.store import create_order, find_orders_by_student, save_receipt
from payments.gateway import charge_student
from notify.sms import send_order_ready

app = Flask(__name__)


@app.route("/orders", methods=["POST"])
def handle_place_order():
    data = request.get_json()
    order = create_order(data["student_id"], data["items"], data["total"])
    paid = charge_student(data["student_id"], data["total"])
    if paid:
        save_receipt(order)
    return jsonify({"order": order, "paid": paid})


@app.route("/orders/<student_id>")
def handle_list_orders(student_id):
    return jsonify(find_orders_by_student(student_id))


@app.route("/orders/<order_id>/ready", methods=["POST"])
def handle_order_ready(order_id):
    phone = request.get_json()["phone"]
    send_order_ready(phone, order_id)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=config.DEBUG)
