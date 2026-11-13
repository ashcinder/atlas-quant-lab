from datetime import date
from decimal import Decimal as D
import pytest
from app.backtest.cn_rules import OpeningMarket, Position, executable_quantity, transaction_cost


def market(**kw):
    values=dict(session=date(2025,1,2),price=D('10'),upper_limit=D('11'),lower_limit=D('9'),suspended=False,limits_known=True)
    values.update(kw)
    return OpeningMarket(**values)


def test_limit_up_down_and_suspension():
    assert executable_quantity('buy',100,'300750.SZ',Position(0,0),market(price=D('11'))).reason=='upper_limit'
    assert executable_quantity('sell',100,'300750.SZ',Position(100,100),market(price=D('9'))).reason=='lower_limit'
    assert executable_quantity('buy',100,'300750.SZ',Position(0,0),market(suspended=True)).reason=='suspended'
    with pytest.raises(ValueError,match='unavailable'):
        executable_quantity('buy',100,'300750.SZ',Position(0,0),market(limits_known=False))


def test_t_plus_one_and_lots_with_star_odd_lot_exit():
    assert executable_quantity('sell',200,'300750.SZ',Position(200,0),market()).reason=='t_plus_one'
    assert executable_quantity('sell',200,'300750.SZ',Position(200,100),market()).quantity==100
    assert executable_quantity('buy',199,'688981.SS',Position(0,0),market()).quantity==0
    assert executable_quantity('buy',201,'688981.SS',Position(0,0),market()).quantity==201
    assert executable_quantity('sell',99,'688981.SS',Position(99,99),market()).quantity==99
    assert executable_quantity('buy',250,'300750.SZ',Position(0,0),market()).quantity==200


def test_stamp_duty_date_and_minimum_commission():
    args=dict(notional=D('10000'),commission_rate=D('0.0003'))
    assert transaction_cost('sell',session=date(2023,8,25),**args)['stamp_duty']==D('10')
    assert transaction_cost('sell',session=date(2023,8,28),**args)['stamp_duty']==D('5')
    assert transaction_cost('buy',session=date(2025,1,1),**args)['total']==D('5.1')
