import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parsePortfolioWords,
  wordsFromTsv,
} from '../src/journal/lib/portfolio-ocr.ts';

const word = (text, x, y, width = 80, height = 24, confidence = 94) => ({
  text,
  confidence,
  x,
  y,
  width,
  height,
});
const near = (actual, expected) =>
  assert.ok(Math.abs(actual - expected) < 0.000001, `${actual} != ${expected}`);

test('portfolio OCR parser reads current value, profit and ROI from a light account screenshot', () => {
  const assets = parsePortfolioWords(
    [
      word('DOGE', 50, 50),
      word('Dogecoin', 50, 82),
      word('1,323.52773544', 780, 50, 180),
      word('¥112.08', 1450, 50, 100),
      word('-¥216.73', 1360, 82, 105),
      word('(-65.92%)', 1470, 82, 100),
      word('ETH', 50, 180),
      word('Ethereum', 50, 212),
      word('0.01129326', 780, 180, 140),
      word('¥27.69', 1450, 180),
      word('-¥23.03', 1360, 212),
      word('(-46.08%)', 1470, 212),
    ],
    1600,
  );
  assert.deepEqual(
    assets.map((asset) => asset.symbol),
    ['DOGE', 'ETH'],
  );
  assert.equal(assets[0].currency, 'CNY');
  near(assets[0].currentValue, 112.08);
  near(assets[0].profit, -216.73);
  near(assets[0].roi, -65.92);
  near(assets[0].invested, 328.81);
});

test('portfolio OCR parser chooses holding value using quantity multiplied by unit price', () => {
  const assets = parsePortfolioWords(
    [
      word('SPY', 50, 45),
      word('State', 50, 78),
      word('0.129921875', 900, 45, 150),
      word('$770.18', 1400, 45),
      word('+$0.11322', 1720, 45, 120),
      word('$100.06', 990, 78),
      word('$769.31', 1400, 78),
    ],
    2000,
  );
  assert.equal(assets.length, 1);
  assert.equal(assets[0].symbol, 'SPY');
  near(assets[0].currentValue, 100.06);
  near(assets[0].profit, 0.11322);
  near(assets[0].invested, 99.94678);
});

test('portfolio OCR TSV reader keeps only recognized word rows and their positions', () => {
  const tsv = [
    'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext',
    '4\t1\t1\t1\t1\t0\t0\t0\t0\t0\t-1\t',
    '5\t1\t1\t1\t1\t1\t42\t90\t55\t20\t96.5\tBTC',
  ].join('\n');
  assert.deepEqual(wordsFromTsv(tsv), [word('BTC', 42, 90, 55, 20, 96.5)]);
});
