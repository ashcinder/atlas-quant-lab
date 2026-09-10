import { ColorType, type IChartApi } from 'lightweight-charts'

export function bindChartTheme(chart: IChartApi) {
  const apply = () => {
    const light = ['white', 'mist'].includes(document.documentElement.dataset.theme ?? '')
    const styles = getComputedStyle(document.documentElement)
    const background = light ? styles.getPropertyValue('--panel').trim() : '#0b0f14'
    const border = light ? '#d7e0ea' : '#253140'
    chart.applyOptions({ layout: { background: { type: ColorType.Solid, color: background || '#fff' }, textColor: light ? '#475569' : '#8b98a8', panes: { separatorColor: border, separatorHoverColor: light ? '#b9c8da' : '#39485b' } }, grid: { vertLines: {color: border}, horzLines: {color: border} }, rightPriceScale: {borderColor:border}, timeScale:{borderColor:border} })
  }
  apply(); window.addEventListener('atlas-appearance-change', apply)
  return () => window.removeEventListener('atlas-appearance-change', apply)
}
