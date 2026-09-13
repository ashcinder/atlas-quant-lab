"""Functional test strategy. Run on the developer's machine, never upload this file."""


def decide(context):
    book = context["book"]
    if float(book["bidPrice"]) <= 0 or float(book["askPrice"]) < float(book["bidPrice"]):
        raise ValueError("Invalid market book")
    return "0.1" if context["step"] % 2 == 0 else "0"
