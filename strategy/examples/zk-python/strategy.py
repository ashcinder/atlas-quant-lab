def target_bps(index, close, sma):
    # Closed-bar count alternates 0% / 10%; next-open execution includes costs.
    return (index % 2) * 1000
