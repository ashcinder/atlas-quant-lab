import AppKit
import Foundation
import WebKit

struct ProbeError: Error, CustomStringConvertible {
    var description: String
    init(_ description: String) { self.description = description }
}

@MainActor
final class LoopbackNavigation: NSObject, WKNavigationDelegate {
    let origin: URL
    init(origin: URL) { self.origin = origin }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction) async -> WKNavigationActionPolicy {
        guard let url = navigationAction.request.url else { return .cancel }
        return url.scheme == origin.scheme && url.host == origin.host && url.port == origin.port ? .allow : .cancel
    }
}

struct Check {
    let hash: String
    let ready: String
    let trigger: String
    let after: String
}

@MainActor
func run() async throws {
    let args = CommandLine.arguments
    guard args.count == 4 else {
        throw ProbeError("usage: wkzoom <run-manifest> <evidence-output-dir> <synthetic-user>")
    }
    let manifestURL = URL(fileURLWithPath: args[1])
    let out = URL(fileURLWithPath: args[2], isDirectory: true)
    let manifest = try JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: Any] ?? [:]
    guard manifest["synthetic_only"] as? Bool == true,
          let originStr = manifest["origin"] as? String, let origin = URL(string: originStr),
          origin.scheme == "http", origin.host == "127.0.0.1",
          let port = origin.port, port != 18095,
          args[3].range(of: #"^user[0-9]{2}$"#, options: .regularExpression) != nil
    else { throw ProbeError("refusing non-isolated target or non-synthetic user") }
    let password = ProcessInfo.processInfo.environment["ATLAS_E2E_PASSWORD"] ?? "Only-E2E-Fixture-2026!"
    try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
    let config = WKWebViewConfiguration()
    config.websiteDataStore = .nonPersistent()
    config.userContentController.addUserScript(WKUserScript(source: """
      window.__zoomProbeErrors = [];
      addEventListener('error', e => window.__zoomProbeErrors.push(e.error?.name || 'error'));
      addEventListener('unhandledrejection', e => window.__zoomProbeErrors.push(e.reason?.name || 'rejection'));
      """, injectionTime: .atDocumentStart, forMainFrameOnly: true))
    let bounds = NSRect(x: 0, y: 0, width: 1440, height: 900)
    let view = WKWebView(frame: bounds, configuration: config)
    let delegate = LoopbackNavigation(origin: origin)
    view.navigationDelegate = delegate
    let window = NSWindow(contentRect: bounds, styleMask: [.borderless], backing: .buffered, defer: true)
    window.contentView = view
    let visible = """
       const shown = n => { const b=n.getBoundingClientRect(),s=getComputedStyle(n);
         return b.width>0 && b.height>0 && s.visibility==='visible' && s.display!=='none'; };
       const pick = (s,t) => Array.from(document.querySelectorAll(s)).find(n => shown(n) &&
          (t===undefined || (n.getAttribute('aria-label') || n.textContent.trim())===t));
       """
    func js(_ source: String) async throws -> Any? {
        try await view.evaluateJavaScript(source)
    }
    func until(_ name: String, _ script: String) async throws -> Any {
        let deadline = Date().addingTimeInterval(15)
        repeat {
            if let value = try? await js(script), !(value is NSNull), (value as? Bool) != false {
                return value
            }
            try await Task.sleep(for: .milliseconds(125))
        } while Date() < deadline
        throw ProbeError("condition timed out: \(name)")
    }
    func measure() async throws -> [String: Any] {
        try await js("""
           ({ width: innerWidth, height: innerHeight, devicePixelRatio,
              scrollWidth: document.documentElement.scrollWidth,
              cssZoom: getComputedStyle(document.documentElement).zoom,
              visualScale: visualViewport?.scale || null })
           """) as? [String: Any] ?? [:]
    }
    let checks = [
        Check(hash: "#single", ready: "pick('.run-button','运行回测')", trigger: "pick('button','回测历史')", after: "pick('[role=dialog][aria-label=回测历史]')"),
        Check(hash: "#portfolio", ready: "pick('h2','多资产组合构建')", trigger: "pick('button','选择资产')", after: "pick('.asset-picker')"),
        Check(hash: "#research", ready: "pick('button','图形化')", trigger: "pick('button','新建策略项目')", after: "pick('.project-editor')"),
        Check(hash: "#quantjudge", ready: "pick('nav','QuantJudge 页面')", trigger: "pick('button','创建策略身份')", after: "pick('.qj-modal')"),
        Check(hash: "#/journal/overview", ready: "pick('button','打开导航')", trigger: "pick('nav[aria-label=资产总览导航] button','定投计划')", after: "location.hash.includes('/journal/plans')"),
        Check(hash: "#/trading", ready: "pick('h1','策略交易')", trigger: "pick('button','新建运行')", after: "pick('.trade-modal')"),
        Check(hash: "#/proof", ready: "pick('.proof-page h1','ZKP / zkVM 证明验证')", trigger: "pick('.proof-page a[href^=\"#/proof/\"]')", after: "location.hash.startsWith('#/proof/') && Boolean(pick('.proof-page'))"),
    ]
    let file = out.appendingPathComponent("result.json")
    var report: [String: Any] = [
        "engine": "macOS WKWebView", "nativeZoomAPI": "WKWebView.pageZoom", "webKitOnly": true,
        "isolated": true, "origin": originStr, "runID": manifest["run_id"] ?? NSNull(),
        "images": manifest["images"] ?? NSNull(), "windowPresented": false, "rows": [],
        "macOS": ProcessInfo.processInfo.operatingSystemVersionString
    ]
    func write() throws {
        let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: file)
    }
    defer {
        try? write()
        view.stopLoading()
        window.contentView = nil
        withExtendedLifetime(delegate) {}
    }
    view.load(URLRequest(url: origin))
    _ = try await until("login form", "Boolean(document.querySelector('.login-card #login-email'))")
    let at100 = try await measure()
    report["login100"] = at100
    view.pageZoom = 2
    guard abs(view.pageZoom - 2) < 0.00001 else { throw ProbeError("native zoom factor is not 2") }
    _ = try await until("native reflow", "innerWidth < 800 && innerWidth > 600")
    let at200 = try await measure()
    report["login200"] = at200
    guard let w100 = at100["width"] as? Double, let w200 = at200["width"] as? Double,
          abs(w100 / w200 - 2) < 0.03, (at200["cssZoom"] as? String) == "1"
    else { throw ProbeError("native zoom did not halve layout width") }
    let credentials = try JSONSerialization.data(withJSONObject: [args[3] + "@e2e.example.test", password])
    let encoded = String(decoding: credentials, as: UTF8.self)
    let login: String = """
       (() => {
           \(visible)
           const values = \(encoded);
           const fields = ['#login-email','#login-password'].map(s=>pick(s));
           const submit = pick('.login-card button[type=submit]', '登录 Atlas');
           if (!fields.every(Boolean) || !submit) return false;
           fields.forEach((input,i) => {
             Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input, values[i]);
             input.dispatchEvent(new Event('input',{bubbles:true}));
           });
           return true;
       })()
       """
    let filled = try await js(login) as? Bool
    guard filled == true else { throw ProbeError("login controls not visible at 200%") }
    _ = try await js("document.querySelector('.login-card button[type=submit]').click()")
    _ = try await until("logged in", "Boolean(document.querySelector('.run-button')) && !document.querySelector('.login-card')")
    report["loginPassed"] = true
    var rows: [[String: Any]] = []
    for (index, check) in checks.enumerated() {
        var row: [String: Any] = ["route": check.hash, "nativeZoom": view.pageZoom]
        do {
            guard let url = URL(string: originStr + "/?wkzoom=" + String(index) + check.hash) else { throw ProbeError("bad route") }
            view.load(URLRequest(url: url))
            // Full navigations make each dialog check independent without mutating user data.
            _ = try await until("workspace ready", """
              (()=>{\(visible); return location.hash===\(String(reflecting: check.hash)) && Boolean(\(check.ready));})()
              """)
            let layout = try await measure()
            row["layout"] = layout
            guard let width = layout["width"] as? Double, let overflow = layout["scrollWidth"] as? Double,
                  abs(width - w200) <= 2, overflow <= width + 2 else {
                throw ProbeError("workspace document exceeds 200% viewport")
            }
            if check.hash == "#/journal/overview" {
                _ = try await until("journal menu opens", """
                    (()=>{\(visible); const n=pick('button','打开导航'); if(n)n.click(); return Boolean(n);})()
                    """)
                _ = try await until("mobile journal sidebar ready", "Boolean(document.querySelector('.sidebar.mobile-open'))")
            }
            let target = try await until("control visible", """
              (()=>{\(visible);const n=\(check.trigger);if(!n || n.disabled)return false;
                n.scrollIntoView({block:'center',inline:'center'}); const r=n.getBoundingClientRect();
                const x=(r.left+r.right)/2, y=(r.top+r.bottom)/2;
                const top=document.elementFromPoint(x,y);
                return x>=0 && x<innerWidth && y>=0 && y<innerHeight && top && n.contains(top)
                  ? {left:r.left,top:r.top,right:r.right,bottom:r.bottom} : false;
              })()
              """)
            row["controlRect"] = target
            _ = try await js("(()=>{\(visible);const n=\(check.trigger);n.click();return true;})()")
            _ = try await until("control activated", "(()=>{\(visible);return Boolean(\(check.after));})()")
            let errors = try await js("window.__zoomProbeErrors || []") as? [String] ?? []
            row["runtimeErrors"] = errors
            guard errors.isEmpty else { throw ProbeError("unhandled WebKit page errors") }
            row["passed"] = true
        } catch {
            row["passed"] = false
            row["failure"] = String(describing: error)
        }
        rows.append(row)
        report["rows"] = rows
        try write()
    }
    report["passed"] = rows.allSatisfy { $0["passed"] as? Bool == true }
    if report["passed"] as? Bool != true { throw ProbeError("at least one 200% workspace check failed") }
}

let application = NSApplication.shared
application.setActivationPolicy(.prohibited)
Task { @MainActor in
    do { try await run(); exit(0) }
    catch { FileHandle.standardError.write(Data((String(describing: error) + "\n").utf8)); exit(1) }
}
application.run()
