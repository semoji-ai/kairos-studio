import { useEffect, useState } from "react";
import {
  createPresentation, listPresentations, openPresentation, presentationEngines,
  remakePresentation, retryPresentation, revisePresentation,
} from "./api";
import { Emoji } from "./emoji";
import type { PresentationEngines, PresentationJob } from "./api";

const labels = { queued: "대기 중", running: "제작 중", completed: "완료", failed: "실패" };
const supportedDocument = /\.(pdf|docx|hwp|hwpx|md|markdown)$/i;
const styleLabels: Record<string, string> = {
  "quiet-cinematic-editorial": "조용한 시네마틱 에디토리얼",
  adaptive: "자동 설계",
};

/** 완성된 작업 아래: 같은 원고로 다시 만들기 · 수정 요청으로 새 버전 만들기 */
function JobFollowUp({ job, provider, onCreated, onError }: {
  job: PresentationJob; provider: string;
  onCreated: (job: PresentationJob) => void; onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [request, setRequest] = useState("");
  const [sending, setSending] = useState<"" | "remake" | "revise">("");

  async function run(kind: "remake" | "revise") {
    if (sending) return;
    setSending(kind);
    try {
      const created = kind === "remake"
        ? await remakePresentation(job.id, provider)
        : await revisePresentation(job.id, request);
      onCreated(created);
      setRequest(""); setOpen(false);
    } catch (e) {
      onError(e instanceof Error ? e.message : "요청하지 못했습니다");
    } finally {
      setSending("");
    }
  }

  return (
    <div className="job-followup">
      <div className="presentation-result-actions">
        <button className="retry-action" disabled={!!sending}
                title="같은 원고와 설정으로 새로 만듭니다 (지금 결과는 그대로 남습니다)"
                onClick={() => run("remake")}>{sending === "remake" ? "시작하는 중…" : "다시 만들기"}</button>
        <button className="retry-action" disabled={!!sending}
                onClick={() => setOpen(v => !v)}>{open ? "수정 요청 닫기" : "수정 요청"}</button>
      </div>
      {open && <div className="revise-box">
        <textarea value={request} maxLength={2000} rows={3} autoFocus
                  placeholder="예: 표지 사진을 더 밝은 아침 분위기로, 3번 슬라이드 제목을 크게, 마지막 장 문구를 '함께 걸어가는 부모'로"
                  onChange={e => setRequest(e.target.value)} />
        <button className="primary-action" disabled={!request.trim() || !!sending}
                onClick={() => run("revise")}>{sending === "revise" ? "시작하는 중…" : "수정본 만들기"}</button>
        <small>요청한 부분만 고친 새 버전을 만듭니다. 지금 PPT는 그대로 남습니다.</small>
      </div>}
    </div>
  );
}

const providerLabels: Record<string, string> = {
  hybrid: "설계 Opus · 제작 Codex", claude: "Opus", codex: "Codex",
};

export default function PresentationStudio() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [audience, setAudience] = useState("일반 학습자");
  const [slides, setSlides] = useState(10);
  const [aspect, setAspect] = useState<"16:9" | "4:3">("16:9");
  const [tone, setTone] = useState("명료하고 현대적인 교육 자료");
  const [stylePreset, setStylePreset] = useState("quiet-cinematic-editorial");
  const [imageStyle, setImageStyle] = useState("cinematic-documentary");
  // hybrid = Opus가 아트 디렉션(디자인·이미지 프롬프트), Codex가 제작
  const [provider, setProvider] = useState<"hybrid" | "codex" | "claude">("hybrid");
  const [aiImages, setAiImages] = useState(true);
  const [notes, setNotes] = useState(true);
  const [jobs, setJobs] = useState<PresentationJob[]>([]);
  const [engines, setEngines] = useState<PresentationEngines | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // 재시도 요청을 보낸 뒤 서버 응답 전까지 버튼을 잠근다 (두 번 누르기 방지)
  const [retrying, setRetrying] = useState<Set<string>>(new Set());
  useEffect(() => {
    presentationEngines().then(result => {
      setEngines(result);
      setStylePreset(result.default_style || "quiet-cinematic-editorial");
      setImageStyle(result.default_image_style || "cinematic-documentary");
      const selected = result.styles?.find(style => style.id === result.default_style);
      if (selected?.tone) setTone(selected.tone);
    }).catch(() => undefined);
    listPresentations().then(setJobs).catch(() => undefined);
  }, []);
  useEffect(() => {
    const timer = setInterval(() => listPresentations().then(setJobs).catch(() => undefined), 2000);
    return () => clearInterval(timer);
  }, []);

  function pickFile(next: File | null) {
    setDragging(false);
    if (!next) return;
    if (!supportedDocument.test(next.name)) {
      setError("PDF, DOCX, HWP, HWPX 또는 MD 문서만 사용할 수 있습니다");
      return;
    }
    setError("");
    setFile(next);
    if (!title) setTitle(next.name.replace(/\.[^.]+$/, ""));
  }

  async function submit() {
    if (!file || busy) return;
    setBusy(true); setError("");
    try {
      const job = await createPresentation(file, {
        title: title.trim() || file.name.replace(/\.[^.]+$/, ""),
        audience, slide_count: slides, aspect, tone, provider,
        style_preset: stylePreset,
        image_style: imageStyle,
        use_ai_images: aiImages, speaker_notes: notes,
      });
      setJobs(old => [job, ...old.filter(j => j.id !== job.id)]);
      setFile(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "작업을 시작하지 못했습니다");
    } finally { setBusy(false); }
  }

  return (
    <main className="ppt-studio">
      <header className="ppt-header">
        <div>
          <span className="ppt-eyebrow">KAIROS PRESENTATION</span>
          <h1>강의안을 발표 자료로</h1>
          <p>문서의 본문·사진·도표를 보존하고, 핵심 시각 자료는 AI로 설계·생성합니다.</p>
        </div>
        <div className="engine-status">
          <span className={engines?.ppt_master.available ? "ready" : "missing"}><i /> PPT Master</span>
          <span className={engines?.codex_fleet.available ? "ready" : "missing"}><i /> Codex Fleet</span>
          <span className={engines?.prompt_kit.available ? "ready" : "missing"}><i /> Prompt Kit</span>
          <span className={engines?.worker.available ? "ready" : "missing"}><i /> PPT Worker</span>
        </div>
      </header>
      <section className="ppt-grid">
        <div className="ppt-card create-card">
          <h2>새 PPT 만들기</h2>
          <label
            className={`drop-zone ${file ? "has-file" : ""} ${dragging ? "is-dragging" : ""}`}
            onDragEnter={e => { e.preventDefault(); setDragging(true); }}
            onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setDragging(true); }}
            onDragLeave={e => {
              e.preventDefault();
              if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
            }}
            onDrop={e => { e.preventDefault(); pickFile(e.dataTransfer.files?.[0] ?? null); }}
          >
            <input type="file" accept=".pdf,.docx,.hwp,.hwpx,.md,.markdown"
              onChange={e => pickFile(e.target.files?.[0] ?? null)} />
            <span className="drop-icon"><Emoji name={file ? "selected" : "upload"} size={44} /></span>
            <strong>{dragging ? "여기에 놓으세요" : file ? file.name : "강의안 문서를 끌어놓거나 선택하세요"}</strong>
            <small>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : "PDF · DOCX · HWP · HWPX · MD / 최대 100MB"}</small>
          </label>
          <div className="form-grid">
            <label className="span-2">PPT 제목<input value={title} onChange={e => setTitle(e.target.value)} /></label>
            <label>대상 청중<input value={audience} onChange={e => setAudience(e.target.value)} /></label>
            <label>슬라이드 수<input type="number" min={4} max={40} value={slides} onChange={e => setSlides(Number(e.target.value))} /></label>
            <label>화면 비율<select value={aspect} onChange={e => setAspect(e.target.value as "16:9" | "4:3")}>
              <option value="16:9">16:9 와이드</option><option value="4:3">4:3 표준</option>
            </select></label>
            <label>제작 에이전트<select value={provider} onChange={e => setProvider(e.target.value as "hybrid" | "codex" | "claude")}>
              <option value="hybrid">설계 Opus · 제작 Codex (추천)</option>
              <option value="claude">Opus만</option><option value="codex">Codex만</option>
            </select></label>
            <label className="span-2">디자인 스타일<select value={stylePreset} onChange={e => {
              const next = e.target.value;
              setStylePreset(next);
              const selected = engines?.styles?.find(style => style.id === next);
              if (selected?.tone) setTone(selected.tone);
            }}>
              {(engines?.styles ?? [
                { id: "quiet-cinematic-editorial", name: "조용한 시네마틱 에디토리얼" },
                { id: "adaptive", name: "내용에 맞게 자동 설계" },
              ]).map(style => <option key={style.id} value={style.id}>{style.name}</option>)}
            </select>
              <small>{engines?.styles?.find(style => style.id === stylePreset)?.description}</small>
            </label>
            <label className="span-2">디자인 분위기<input value={tone} onChange={e => setTone(e.target.value)} /></label>
            {aiImages && <label className="span-2">AI 이미지 스타일<select value={imageStyle} onChange={e => setImageStyle(e.target.value)}>
              {(engines?.image_styles ?? [
                { id: "cinematic-documentary", name: "시네마틱 다큐멘터리" },
                { id: "editorial-illustration", name: "프리미엄 에디토리얼 일러스트" },
                { id: "minimal-3d", name: "미니멀 매트 3D" },
                { id: "clean-graphic", name: "클린 에디토리얼 그래픽" },
              ]).map(style => <option key={style.id} value={style.id}>{style.name}</option>)}
            </select>
              <small>{engines?.image_styles?.find(style => style.id === imageStyle)?.description ?? "모든 생성 이미지에 같은 매체·조명·색감·질감을 적용합니다."}</small>
            </label>}
          </div>
          <div className="toggle-row">
            <label><input type="checkbox" checked={aiImages} onChange={e => setAiImages(e.target.checked)} /> 고품질 AI 이미지·삽화 생성</label>
            <label><input type="checkbox" checked={notes} onChange={e => setNotes(e.target.checked)} /> 발표자 노트 작성</label>
          </div>
          {error && <div className="ppt-error">{error}</div>}
          <button className="primary-action" disabled={!file || busy} onClick={submit}>{busy ? "업로드 중…" : "PPT 제작 시작"}</button>
        </div>
        <div className="ppt-card jobs-card">
          <div className="jobs-title"><div><h2>제작 작업 · 히스토리</h2><small>앱을 재시작해도 이 기기에 계속 보존됩니다.</small></div><span>{jobs.length}</span></div>
          <div className="job-list">
            {!jobs.length && <div className="empty-jobs"><Emoji name="empty" size={64} /><p>아직 제작한 PPT가 없습니다.</p></div>}
            {jobs.map(job => <article className="job-item" key={job.id}>
              <div className="job-row"><div><strong>{job.title}</strong><small>{job.source_name} · {providerLabels[job.provider] ?? job.provider} · {styleLabels[job.options?.style_preset ?? ""] ?? job.options?.tone ?? "기존 스타일"}</small>
                {job.options?.image_style && <small>AI 이미지 · {engines?.image_styles?.find(style => style.id === job.options?.image_style)?.name ?? job.options.image_style}</small>}
                <small>{new Date(job.created_at).toLocaleString("ko-KR")}</small>
                {job.revision_request && <small className="job-revision">수정 요청: {job.revision_request}</small>}</div>
                <span className={`job-status ${job.status}`}>{labels[job.status]}</span></div>
              <div className="progress-track"><span style={{ width: `${job.progress ?? 0}%` }} /></div>
              <div className="job-stage"><span>{job.stage}</span><b>{job.progress ?? 0}%</b></div>
              {job.error && <div className="job-error">{job.error}</div>}
              {!!job.log?.length && <details><summary>작업 로그</summary><pre>{job.log.slice(-80).join("")}</pre></details>}
              {(job.status === "queued" || job.status === "running" || retrying.has(job.id)) ? (
                <button className="retry-action" disabled>제작 중…</button>
              ) : job.status === "failed" && <button className="retry-action" onClick={async () => {
                setRetrying(old => new Set(old).add(job.id));
                try {
                  const retried = await retryPresentation(job.id);
                  setJobs(old => old.map(item => item.id === retried.id ? retried : item));
                } catch (e) {
                  setError(e instanceof Error ? e.message : "재시도하지 못했습니다");
                } finally {
                  setRetrying(old => { const next = new Set(old); next.delete(job.id); return next; });
                }
              }}>이 작업 다시 시도</button>}
              {job.status === "completed" && <div className="presentation-result-actions">
                <button className="download-action" onClick={async () => {
                  setError(""); setNotice("");
                  try {
                    const result = await openPresentation(job);
                    setNotice(`PowerPoint를 열었습니다 · ${result.path}`);
                  } catch (e) {
                    setError(e instanceof Error ? e.message : "PowerPoint를 열지 못했습니다");
                  }
                }}>PowerPoint 열기</button>
                <button className="retry-action" onClick={async () => {
                  setError(""); setNotice("");
                  try {
                    const result = await openPresentation(job, true);
                    setNotice(`파일 위치를 열었습니다 · ${result.path}`);
                  } catch (e) {
                    setError(e instanceof Error ? e.message : "파일 위치를 열지 못했습니다");
                  }
                }}>폴더 열기</button>
              </div>}
              {job.status === "completed" && <JobFollowUp job={job} provider={provider}
                onCreated={created => {
                  setJobs(old => [created, ...old]);
                  setNotice(created.revision ? `수정본 제작을 시작했습니다 · ${created.title}` : `다시 만들기를 시작했습니다 · ${created.title}`);
                }}
                onError={message => setError(message)} />}
            </article>)}
          </div>
          {notice && <div className="ppt-notice">{notice}</div>}
        </div>
      </section>
    </main>
  );
}
