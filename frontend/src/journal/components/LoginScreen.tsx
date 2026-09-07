import { useState } from 'react';
import { ChartCandlestick, UserPlus, LogIn, Mail, LockKeyhole, ShieldCheck } from 'lucide-react';
import { Input } from './ui/input';
import { Button } from './ui/button';
const errorText = (error: unknown) => error instanceof Error ? error.message : '请求失败，请重试';
export default function LoginScreen({
  busy,
  error,
  registrationEnabled,
  onAuthenticate,
}: {
  busy: boolean;
  error: string;
  registrationEnabled: boolean;
  onAuthenticate: (
    mode: "login" | "register",
    email: string,
    password: string,
  ) => Promise<void>;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [formError, setFormError] = useState("");
  const register = mode === "register";
  const switchMode = (next: "login" | "register") => {
    setMode(next);
    setPassword("");
    setConfirmation("");
    setFormError("");
  };
  return (
    <main className="login-page">
      <section className="login-story" aria-hidden="true">
        <div className="login-brand">
          <ChartCandlestick size={30} />
          <span>
            Atlas <small>Quant Lab</small>
          </span>
        </div>
        <div className="login-copy">
          
          <h1>研究策略，也管理资产。</h1>
          <p>行情与策略回测、资产账本与定投计划，在同一个工作台。</p>
        </div>
        <div className="login-capabilities"><span>行情 · 回测 · 组合研究</span><span>账户 · 资产 · 定投手账</span></div>
      </section>
      <section className="login-panel">
        <form
          className="login-card"
          onSubmit={(event) => {
            event.preventDefault();
            setFormError("");
            if (register && password !== confirmation) {
              setFormError("两次输入的密码不一致");
              return;
            }
            void onAuthenticate(mode, email, password).catch((cause) =>
              setFormError(errorText(cause)),
            );
          }}
        >
          <span className="login-mark">
            {register ? <UserPlus size={23} /> : <LogIn size={23} />}
          </span>
          <div>
            
            <h2>{register ? "创建 Atlas 账号" : "欢迎回来"}</h2>
            <p>
              {register
                ? "创建账号，开始策略研究与个人资产记录。"
                : "登录后继续你的策略研究与资产记录。"}
            </p>
          </div>
          <label htmlFor="login-email">
            <span>登录邮箱</span>
            <span className="login-input">
              <Mail size={17} />
              <Input
                id="login-email"
                type="email"
                autoComplete="email"
                placeholder="name@example.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </span>
          </label>
          <label htmlFor="login-password">
            <span>密码</span>
            <span className="login-input">
              <LockKeyhole size={17} />
              <Input
                id="login-password"
                type="password"
                autoComplete={register ? "new-password" : "current-password"}
                minLength={register ? 8 : undefined}
                maxLength={128}
                placeholder={register ? "至少 8 个字符" : "输入密码"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </span>
          </label>
          {register && (
            <label htmlFor="register-password-confirmation">
              <span>确认密码</span>
              <span className="login-input">
                <ShieldCheck size={17} />
                <Input
                  id="register-password-confirmation"
                  type="password"
                  autoComplete="new-password"
                  minLength={8}
                  maxLength={128}
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  placeholder="再次输入密码"
                  required
                />
              </span>
            </label>
          )}
          {(formError || error) && (
            <p className="login-error" role="alert">{formError || error}</p>
          )}
          <Button type="submit" className="primary-button" disabled={busy}>
            {busy
              ? register
                ? "正在创建…"
                : "正在验证…"
              : register
                ? "注册并进入 Atlas"
                : "登录 Atlas"}
          </Button>
          {registrationEnabled && (
            <div className="auth-switch">
              <span>{register ? "已经有账号？" : "第一次使用 Atlas？"}</span>
              <button
                type="button"
                disabled={busy}
                onClick={() => switchMode(register ? "login" : "register")}
              >
                {register ? "返回登录" : "创建账号"}
              </button>
            </div>
          )}
          <small className="login-security">
            <ShieldCheck size={13} /> 密码安全存储，每个账号的数据相互隔离
          </small>
        </form>
      </section>
    </main>
  );
}
