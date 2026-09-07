import test from 'node:test';
import assert from 'node:assert/strict';
import { seedLedger, validateLedger, portfolio } from '../src/journal/domain/ledger.ts';
import { validAccountImage, ACCOUNT_IMAGE_MAX_LENGTH } from '../src/journal/domain/account-image.ts';

export const icon = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=';

test('account images survive JSON backup and removal without changing investments', () => {
  let s = seedLedger('2026-09-04');
  const before = portfolio(s).value;
  validateLedger(s); // Older accounts have no image property.
  s.accounts[0].image = icon;
  s = validateLedger(JSON.parse(JSON.stringify(s)));
  assert.equal(s.accounts[0].image, icon);
  assert.equal(s.accounts[1].image, undefined);
  assert.equal(portfolio(s).value, before);
  delete s.accounts[0].image;
  validateLedger(s);
  assert.equal(s.accounts[0].image, undefined);
});

test('ledger rejects oversized, external, vector and invalid image payloads', () => {
  for (const image of [null, '', 'https://example.com/a.png', 'data:image/svg+xml;base64,PHN2Zz4=',
    'data:image/png;base64,YWJj', 'data:image/jpeg;base64,iVBORw0KGgo=',
    icon + 'A'.repeat(ACCOUNT_IMAGE_MAX_LENGTH)]) {
    assert.equal(validAccountImage(image), false);
    const s = seedLedger('2026-09-04');
    s.accounts[0].image = image;
    assert.throws(() => validateLedger(s), /账户图片/);
  }
});
