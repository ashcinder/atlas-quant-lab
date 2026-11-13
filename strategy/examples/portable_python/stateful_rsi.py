"""Standard Python with functions, loops and persistent strategy state."""
def initialize(context):
    context.state['holding'] = False


def target(context):
    if len(context.close) < 15:
        return 0.0
    changes = [b-a for a,b in zip(context.close[-15:-1], context.close[-14:])]
    gain = sum(max(value, 0) for value in changes) / 14
    loss = sum(max(-value, 0) for value in changes) / 14
    rsi = 100 if loss == 0 else 100 - 100/(1+gain/loss)
    if rsi < 35:
        context.state['holding'] = True
    elif rsi > 65:
        context.state['holding'] = False
    return 0.75 if context.state['holding'] else 0.0
