from datetime import datetime, timedelta


def calculate_sessionnet_params():
    """
    Calculate parameters for SessionNet.
    __cmonat = Month from exactly 6 months ago
    """
    now = datetime.now()
    six_months_ago = now - timedelta(days=180)

    return {
        "__cjahr": now.year,
        "__cmonat": six_months_ago.month,
        "__canz": 6,
        "smccont": 12,
        "__cselect": 81920
    }