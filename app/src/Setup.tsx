import { useEffect, useRef, useState } from "react";
import { installCli, installWorkspace, openLogin, putSettings, setupStatus } from "./api";
import type { SetupStatus } from "./api";
import { Emoji } from "./emoji";

// 앱을 켤 때 로그인이 풀려 있으면 로그인 페이지를 한 번만 자동으로 연다
// (화면이 다시 그려져도 앱 실행당 한 번).
let autoLoginOpened = false;
const LOGIN_POLL_MS = 3000;
const LOGIN_POLL_LIMIT_MS = 10 * 60 * 1000;

export default function Setup({ onDone }: { onDone: () => void }) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [installing, setInstalling] = useState(false);
  const [installResult, setInstallResult] = useState<{ ok: boolean; tail?: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const [wsInstalling, setWsInstalling] = useState(false);
  const [wsResult, setWsResult] = useState<{ workspace_dir: string; skills: number } | null>(null);
  const [wsError, setWsError] = useState<string | null>(null);
  const [permBumped, setPermBumped] = useState(false);
  const [loginOpened, setLoginOpened] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const loginStartedAt = useRef<number | null>(null);

  function refresh() {
    return setupStatus().then(setStatus);
  }

  useEffect(() => { refresh(); }, []);

  async function doInstallCli() {
    setInstalling(true); setInstallResult(null);
    try {
      const res = await installCli();
      setInstallResult(res);
    } finally {
      setInstalling(false);
      await refresh();
    }
  }

  async function doOpenLogin() {
    setLoginError(null);
    const res = await openLogin().catch(e => ({ ok: false, error: String(e) }));
    if (!res.ok) {
      setLoginError(res.error || "로그인 창을 열지 못했습니다.");
      return;
    }
    loginStartedAt.current = Date.now();
    setLoginOpened(true);
  }

  async function doCheck() {
    setChecking(true);
    try { await refresh(); } finally { setChecking(false); }
  }

  async function doInstallWorkspace() {
    setWsInstalling(true); setWsError(null); setWsResult(null);
    try {
      const res = await installWorkspace();
      setWsResult(res);
      await refresh();
    } catch (e) {
      setWsError(e instanceof Error ? e.message : String(e));
    } finally {
      setWsInstalling(false);
    }
  }

  async function bumpPermission() {
    await putSettings({ claude_permission_mode: "acceptEdits" });
    setPermBumped(true);
  }

  const claude = status?.cli?.claude;
  const installed = !!claude?.installed;
  const authed = !!claude?.authed;

  // 로그인이 풀려 있으면 로그인 페이지를 자동으로 연다
  useEffect(() => {
    if (status && installed && !authed && !autoLoginOpened) {
      autoLoginOpened = true;
      doOpenLogin();
    }
  }, [status, installed, authed]);

  // 로그인 창을 연 뒤에는 몇 초마다 확인해 끝나면 저절로 '완료'로 바뀐다
  useEffect(() => {
    if (!loginOpened || authed) return;
    const timer = window.setInterval(() => {
      const started = loginStartedAt.current ?? Date.now();
      if (Date.now() - started > LOGIN_POLL_LIMIT_MS) {
        window.clearInterval(timer);
        return;
      }
      refresh().catch(() => {});
    }, LOGIN_POLL_MS);
    return () => window.clearInterval(timer);
  }, [loginOpened, authed]);

  // 로그인 때문에 이 화면이 떴던 거라면, 로그인이 끝나고 모두 준비되면 바로 시작한다
  useEffect(() => {
    if (loginOpened && authed && status?.all_ready) onDone();
  }, [loginOpened, authed, status?.all_ready]);

  return (
    <main className="page">
      <div className="page-inner narrow">
      <header className="page-header">
        <div>
          <span className="page-eyebrow">KAIROS STUDIO</span>
          <h1>카이로스 스튜디오 첫 실행 설정</h1>
        </div>
      </header>

      <section className="card">
        <h3><span className="setup-step">1</span> Claude 설치
          {installed && <span className="setup-done"><Emoji name="done" size={18} /> 완료</span>}</h3>
        {installed ? (
          <p className="hint">설치되어 있습니다{claude?.version ? ` (${claude.version})` : ""}.</p>
        ) : (
          <div className="stack">
            <div><button className="btn-primary" disabled={installing} onClick={doInstallCli}>
              {installing ? "설치 중..." : "설치하기"}
            </button></div>
            {installResult && (installResult.ok ? (
              <div className="notice ok">설치 완료</div>
            ) : (
              <div className="notice error">
                설치 실패. 수동 설치가 필요할 수 있습니다.
                {installResult.tail && <pre>{installResult.tail}</pre>}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <h3><span className="setup-step">2</span> 로그인
          {authed && <span className="setup-done"><Emoji name="done" size={18} /> 완료</span>}</h3>
        {authed ? (
          <p className="hint">로그인되어 있습니다.</p>
        ) : (
          <div className="stack">
            {loginOpened && (
              <p className="hint">
                브라우저에 Claude 로그인 페이지를 열었습니다. 로그인하시면 자동으로 넘어갑니다.
              </p>
            )}
            {loginError && <div className="notice error">{loginError}</div>}
            <div className="field-row">
              <button className="btn-primary" onClick={doOpenLogin} disabled={!installed}>
                {loginOpened ? "로그인 페이지 다시 열기" : "로그인 페이지 열기"}
              </button>
              <button disabled={checking} onClick={doCheck}>
                {checking ? "확인 중..." : "다시 확인"}
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="card">
        <h3><span className="setup-step">3</span> 설교 도우미 (선택)
          {status?.workspace_ready && <span className="setup-done"><Emoji name="done" size={18} /> 완료</span>}</h3>
        {status?.workspace_ready ? (
          <p className="hint">스킬 사용 가능. 작업 폴더: {status.workspace_dir}</p>
        ) : (
          <div className="stack">
            <div><button disabled={wsInstalling} onClick={doInstallWorkspace}>
              {wsInstalling ? "설치 중..." : "설치"}
            </button></div>
            {wsError && <div className="notice error">{wsError}</div>}
          </div>
        )}
        {wsResult && (
          <div className="stack" style={{ marginTop: 12 }}>
            <div className="status-ok">스킬 {wsResult.skills}개 설치됨.</div>
            <div className="field-row hint">
              스킬이 파일을 쓰려면 권한을 acceptEdits로 올리는 것을 권장합니다.
              <button disabled={permBumped} onClick={bumpPermission}>
                {permBumped ? "권한 상향됨" : "권한 올리기"}
              </button>
            </div>
          </div>
        )}
      </section>

      <button className="btn-primary setup-start" disabled={!status?.all_ready} onClick={onDone}>
        시작하기
      </button>
      </div>
    </main>
  );
}
