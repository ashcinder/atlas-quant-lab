import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BacktestPeriod } from './BacktestPeriod'
afterEach(cleanup)
it('applies only on explicit confirmation and preserves original dates when cancelled',()=>{
 HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','')};HTMLDialogElement.prototype.close=function(){this.removeAttribute('open')}
 const apply=vi.fn();render(<BacktestPeriod start="2025-01-01T00:00" end="2025-02-01T00:00" onApply={apply}/>);
 fireEvent.click(screen.getByRole('button',{name:/回测时间区间/}));fireEvent.input(screen.getByLabelText('回测开始时间'),{target:{value:'2025-01-15T00:00'}});expect(apply).not.toHaveBeenCalled();fireEvent.click(screen.getByText('取消'));expect(apply).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:/回测时间区间/}));expect((screen.getByLabelText('回测开始时间') as HTMLInputElement).value).toBe('2025-01-01T00:00');fireEvent.click(screen.getByText('确认区间'));expect(apply).toHaveBeenCalledWith('2025-01-01T00:00','2025-02-01T00:00')
})
