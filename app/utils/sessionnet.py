from datetime import datetime, timedelta


def calculate_sessionnet_params():
    """
    Calculate parameters for SessionNet.
    __cmonat = Month from exactly 6 months ago
    """
    now = datetime.now()
    six_months_ago = now - timedelta(days=180)

    return {
        "__cjahr": six_months_ago.year,
        "__cmonat": six_months_ago.month,
        "__canz": 12, # 12 months, to make sure we get all protocols up to date
        "smccont": 12,
        "__cselect": 81920
    }