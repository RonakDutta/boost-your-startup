"""Sends 'your order is ready' text messages."""
import requests

import config


def send_order_ready(phone, order_id):
    message = f"Your CampusEats order {order_id} is ready for pickup."
    for attempt in range(3):
        try:
            requests.get(config.SMS_API_URL, params={"to": phone, "text": message})
            return True
        except Exception:
            continue
    return False
