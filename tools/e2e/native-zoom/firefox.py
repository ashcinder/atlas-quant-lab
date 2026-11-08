"""Firefox native zoom verification in a disposable profile, using built-in Marionette."""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse


class Marionette:
    def __init__(self, connection: socket.socket):
        self.connection = connection
        self.stream = connection.makefile('rb')
        self.counter = 0
        greeting = self.receive()
        assert greeting.get('marionetteProtocol') == 3, greeting

    def receive(self):
        size = bytearray()
        while (char := self.stream.read(1)) != b':':
            if not char:
                raise EOFError('Marionette disconnected')
            size.extend(char)
        return json.loads(self.stream.read(int(size)))

    def call(self, name, **params):
        self.counter += 1
        data = json.dumps([0, self.counter, name, params]).encode()
        self.connection.sendall(str(len(data)).encode() + b':' + data)
        message_type, request_id, error, result = self.receive()
        if message_type != 1 or request_id != self.counter or error:
            raise RuntimeError(f'{name} failed: {error}')
        return result

    def script(self, script, *args):
        return self.call('WebDriver:ExecuteScript', script=script, args=list(args), newSandbox=True)['value']

    def until(self, fn, label, seconds=15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = fn()
            if result:
                return result
            time.sleep(.15)
        raise AssertionError(label)


ROUTES = {
    'single': ('#single', '运行回测'),
    'portfolio': ('#portfolio', '选择资产'),
    'research': ('#research', '新建策略项目'),
    'quantjudge': ('#quantjudge', '创建策略身份'),
    'journal': ('#/journal/overview', '记一笔'),
    'trading': ('#/trading', '新建运行'),
}

MATCH = '''
const label = arguments[0];
const active = Array.from(document.querySelectorAll('button,a')).filter(node =>
  node.getClientRects().length > 0 && getComputedStyle(node).visibility === 'visible'
  && !node.matches(':disabled') && !node.closest('[hidden], [aria-hidden="true"]')
  && (node.getAttribute('aria-label') || node.innerText).trim() === label);
if (!active.length) return null;
const node = active[0];
node.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
return true;
'''

POSITION = '''
const label = arguments[0];
const active = Array.from(document.querySelectorAll('button,a')).filter(node =>
  node.getClientRects().length > 0 && getComputedStyle(node).visibility === 'visible'
  && !node.matches(':disabled') && !node.closest('[hidden], [aria-hidden="true"]')
  && (node.getAttribute('aria-label') || node.innerText).trim() === label);
if (!active.length) return null;
const node = active[0], rect = node.getBoundingClientRect();
const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
const hit = document.elementFromPoint(x, y);
return { label, width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth,
  element: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
  inside: rect.left >= -1 && rect.right <= innerWidth + 1 && rect.top >= -1 && rect.bottom <= innerHeight + 1,
  hit: hit === node || node.contains(hit),
  hitElement: hit?.tagName ?? null, hitClass: (typeof hit?.className === 'string' ? hit.className : null),
};
'''


def native_zoom(driver, value):
    driver.call('Marionette:SetContext', value='chrome')
    try:
        return driver.script('''
          FullZoom.setZoom(arguments[0], gBrowser.selectedBrowser);
          return {fullZoom: gBrowser.selectedBrowser.fullZoom,
                  textZoom: gBrowser.selectedBrowser.textZoom, useFullZoom: ZoomManager.useFullZoom};
        ''', value)
    finally:
        driver.call('Marionette:SetContext', value='content')


def read_zoom(driver):
    driver.call('Marionette:SetContext', value='chrome')
    try:
        return driver.script('return gBrowser.selectedBrowser.fullZoom')
    finally:
        driver.call('Marionette:SetContext', value='content')


def probe(driver, manifest, fixture, output):
    origin = manifest['origin']
    session = driver.call('WebDriver:NewSession', capabilities={'alwaysMatch': {}})
    driver.call('WebDriver:SetWindowRect', width=1440, height=900)
    driver.call('WebDriver:Navigate', url=origin)
    driver.until(lambda: driver.script("return !!document.querySelector('input[type=email]')"), 'login not ready')
    password = os.environ.get('ATLAS_E2E_PASSWORD', 'Only-E2E-Fixture-2026!')
    login = driver.call('WebDriver:ExecuteAsyncScript', script='''
      const done = arguments[arguments.length - 1];
      fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({email:'user96@e2e.example.test', password:arguments[0]})})
      .then(result => done(result.status), () => done(null));
    ''', args=[password], newSandbox=True)
    assert login['value'] == 200, 'synthetic fixture login failed'
    driver.call('WebDriver:Refresh')
    driver.call('WebDriver:Navigate', url=origin+'/#single')
    driver.until(lambda: driver.script("return !document.querySelector('input[type=email]') && !!document.querySelector('.topbar')"), 'not authenticated')
    initial_zoom = native_zoom(driver, 1)
    before = driver.script('return {width: innerWidth, height: innerHeight, dpr: devicePixelRatio}')
    zoom = native_zoom(driver, 2)
    assert initial_zoom['fullZoom'] == 1 and zoom == {'fullZoom': 2, 'textZoom': 1, 'useFullZoom': True}, zoom
    driver.until(lambda: driver.script('return innerWidth') <= before['width'] * .51, 'native layout did not reflow')
    after = driver.script('return {width: innerWidth, height: innerHeight, dpr: devicePixelRatio}')
    assert abs(2 * after['width'] - before['width']) <= 2, (before, after)

    rows = []
    for name, (route, control) in (ROUTES | {'proof': ('#/proof/' + fixture['proof_id'], '验证 Proof')}).items():
        try:
            driver.script('location.hash = arguments[0]', route)
            driver.until(lambda: driver.script('return location.hash') == route, name+' route unavailable')
            driver.until(lambda: driver.script(MATCH, control), name+' control unavailable')
            position = driver.script(POSITION, control)
            row = {'workspace': name, 'native_zoom': read_zoom(driver), **position}
            screenshot = driver.call('WebDriver:TakeScreenshot', full=False)['value']
            (output / (name + '.png')).write_bytes(base64.b64decode(screenshot))
            row['pass'] = row['native_zoom'] == 2 and row['inside'] and row['hit'] and row['scrollWidth'] <= row['width'] + 1
        except (RuntimeError, AssertionError) as exc:
            row = {'workspace': name, 'pass': False, 'error': str(exc)}
        rows.append(row)
    result = {
        'run_id': manifest['run_id'], 'browser': 'Playwright-bundled Firefox / native FullZoom browser chrome',
        'browser_version': session['capabilities']['browserVersion'],
        'images': manifest['images'], 'before': before, 'after': after, 'native': zoom,
        'workspaces': rows, 'passed': all(row['pass'] for row in rows),
    }
    (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False))
    return result['passed']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path, help='Synthetic Docker run.json')
    parser.add_argument('firefox', type=Path, help='Playwright Firefox binary')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.run.read_text())
    fixture = json.loads(args.run.with_name('fixture.json').read_text())
    origin = urlparse(manifest['origin'])
    assert manifest['synthetic_only'] and fixture['synthetic_only'] and origin.scheme == 'http'
    assert origin.hostname == '127.0.0.1' and origin.port not in (None, 18095) and origin.port == manifest['port']
    assert 'user96' in fixture['accounts'] and fixture.get('proof_id')
    args.output.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(prefix='atlas-gecko-profile-') as profile:
        with socket.socket() as port_socket:
            port_socket.bind(('127.0.0.1', 0))
            port = port_socket.getsockname()[1]
        (Path(profile) / 'user.js').write_text(f'''
user_pref("marionette.port", {port});
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.newtabpage.enabled", false);
user_pref("browser.zoom.full", true);
user_pref("browser.zoom.siteSpecific", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("network.captive-portal-service.enabled", false);
''')
        env = {**os.environ, 'MOZ_REMOTE_ALLOW_SYSTEM_ACCESS': '1', 'CFFIXED_USER_HOME': profile}
        with (args.output/'firefox.log').open('wb') as log:
            firefox = subprocess.Popen([str(args.firefox), '-headless', '-no-remote', '-profile', profile,
                                        '--marionette', 'about:blank'], env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(120):
                    try:
                        conn = socket.create_connection(('127.0.0.1', port), timeout=1)
                        break
                    except OSError:
                        if firefox.poll() is not None:
                            raise RuntimeError('Firefox quit before Marionette was ready')
                        time.sleep(.15)
                else:
                    raise RuntimeError('Marionette did not become ready')
                with conn:
                    conn.settimeout(30)
                    return 0 if probe(Marionette(conn), manifest, fixture, args.output) else 1
            finally:
                firefox.terminate()
                try:
                    firefox.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    firefox.kill()
                    firefox.wait()
                subprocess.run(['chmod', '-RN', profile], check=True)


if __name__ == '__main__':
    raise SystemExit(main())
