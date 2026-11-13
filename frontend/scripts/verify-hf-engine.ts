/** Run the production browser engine under Node for repeatable data acceptance. */
import { readFileSync } from 'node:fs'
import { runBacktest } from '../src/compute/backtest'
const { request, market } = JSON.parse(readFileSync(0, 'utf8'))
const result = await runBacktest(request, market)
process.stdout.write(JSON.stringify(result))
