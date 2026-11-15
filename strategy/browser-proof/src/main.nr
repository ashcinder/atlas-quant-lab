// atlas-browser-sma-v1: 32 closed candles, long-only, 95% target,
// 10 bps commission, 5 bps slippage, and a starting balance of 10,000.
global BARS: u32 = 32;
global MAX_PERIOD: u32 = 16;
global MICRO: u64 = 1000000;
global INITIAL: u64 = 10000 * MICRO;

fn main(
    market_hash: pub [Field; 2],
    opens: pub [u64; BARS],
    closes: pub [u64; BARS],
    fast: u32,
    slow: u32,
    salt: Field,
) -> pub [Field; 2] {
    assert(fast >= 2 & fast < slow & slow <= MAX_PERIOD);
    assert(salt != 0);
    let mut cash = INITIAL;
    let mut quantity = 0 as u64;

    for i in 0..BARS {
        let open = opens[i];
        let close = closes[i];
        assert(open > 0 & close > 0);

        // The execution at bar i can see only closes from bars before i.
        let mut fast_sum = 0 as u64;
        let mut slow_sum = 0 as u64;
        for offset in 1..(MAX_PERIOD + 1) {
            if i >= offset {
                let previous = closes[i - offset];
                if offset <= fast { fast_sum += previous; }
                if offset <= slow { slow_sum += previous; }
            }
        }
        let bullish = i >= slow & fast_sum * slow as u64 > slow_sum * fast as u64;
        let equity_at_open = cash + quantity * open / MICRO;
        let target_notional = if bullish { equity_at_open * 9500 / 10000 } else { 0 };
        let desired = target_notional * MICRO / open;
        if desired > quantity {
            let buy_price = open * 10005 / 10000;
            let notional = (desired - quantity) * buy_price / MICRO;
            cash -= notional + notional * 10 / 10000;
        } else {
            let sell_price = open * 9995 / 10000;
            let notional = (quantity - desired) * sell_price / MICRO;
            cash += notional - notional * 10 / 10000;
        }
        quantity = desired;
    }
    let final_equity = cash + quantity * closes[BARS - 1] / MICRO;
    assert(final_equity > 0);
    let commitment = std::hash::pedersen_hash([
        market_hash[0], market_hash[1], fast as Field, slow as Field, salt,
    ]);
    [final_equity as Field, commitment]
}
