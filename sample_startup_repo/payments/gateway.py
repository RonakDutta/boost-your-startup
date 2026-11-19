"""Charges a student's wallet through the payment provider."""
import requests

import config


def charge_student(student_id, amount):
    """Returns True when the payment went through."""
    try:
        response = requests.post(
            config.PAYMENT_API_URL,
            json={"customer": student_id, "amount": int(amount * 100)},
            headers={"Authorization": "Bearer " + config.PAYMENT_API_KEY},
        )
        return response.json()["status"] == "succeeded"
    except:
        return False


def refund(payment_id):
    response = requests.post(config.PAYMENT_API_URL + "/refund", json={"id": payment_id})
    assert response.status_code == 200, "refund failed"
    return response.json()
