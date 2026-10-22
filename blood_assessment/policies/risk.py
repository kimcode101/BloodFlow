"""Version floor-fefo-v1: fixed operational indicators; no LLM weights."""
def priority(projection, expiry_three_days, evaluated_days):
    if any(row['unmet_demand'] > 0 for row in projection['days'][:evaluated_days]):
        return 100
    return 50 if expiry_three_days else 0
