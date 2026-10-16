// Bias Studio — Frontend Controller
(() => {
  let currentSession = null;
  let maxTurnsMode = 6; // 6Q Quick Mode default (<1 min), toggleable to 10Q
  let pollInterval = null;

  // Pomodoro state
  let timerSeconds = 25 * 60;
  let timerRunning = false;
  let timerTick = null;

  // Audio players for Focus Room
  const djPlayer = new Audio();
  const asmrPlayer = new Audio();
  const bgmPlayer = new Audio();
  bgmPlayer.loop = true;
  bgmPlayer.volume = 0.55;

  // DOM References
  const viewQuestion = document.getElementById("view-question");
  const viewStudio = document.getElementById("view-studio");
  const viewFocus = document.getElementById("view-focus");
  const workspaceRoot = document.getElementById("workspace-root");
  const traceDrawer = document.getElementById("trace-drawer");

  const modeToggleBtn = document.getElementById("mode-toggle-btn");
  const newSessionBtn = document.getElementById("new-session-btn");
  const traceToggleBtn = document.getElementById("trace-toggle-btn");
  const brandHomeBtn = document.getElementById("brand-home-btn");

  const questionProgressLabel = document.getElementById("question-progress-label");
  const questionAxisTag = document.getElementById("question-axis-tag");
  const questionHeadline = document.getElementById("question-headline");
  const optionsList = document.getElementById("options-list");
  const thisOrThatBox = document.getElementById("this-or-that-box");
  const visualCardA = document.getElementById("visual-card-a");
  const visualCardB = document.getElementById("visual-card-b");
  const visualImgA = document.getElementById("visual-img-a");
  const visualImgB = document.getElementById("visual-img-b");
  const visualLabelA = document.getElementById("visual-label-a");
  const visualLabelB = document.getElementById("visual-label-b");

  const customAnswerInput = document.getElementById("custom-answer-input");
  const customAnswerSubmit = document.getElementById("custom-answer-submit");
  const safetyBanner = document.getElementById("safety-banner");
  const safetyReasonText = document.getElementById("safety-reason-text");
  const safetyAltText = document.getElementById("safety-alt-text");

  function showView(viewName) {
    viewQuestion.classList.add("hidden");
    viewStudio.classList.add("hidden");
    viewFocus.classList.add("hidden");
    if (viewName === "question") viewQuestion.classList.remove("hidden");
    if (viewName === "studio") viewStudio.classList.remove("hidden");
    if (viewName === "focus") viewFocus.classList.remove("hidden");
  }

  function renderTrace(traceList) {
    const countEl = document.getElementById("trace-count");
    const totalMsEl = document.getElementById("trace-total-ms");
    const listEl = document.getElementById("trace-list");
    const items = traceList || [];
    countEl.textContent = String(items.length);

    const totalMs = items.reduce((acc, it) => acc + (it.latency_ms || 0), 0);
    totalMsEl.textContent = `${(totalMs / 1000).toFixed(1)}s total`;

    listEl.innerHTML = "";
    items.slice().reverse().forEach((entry) => {
      const div = document.createElement("div");
      div.className = "trace-item";
      div.innerHTML = `
        <div class="trace-item-top">
          <span>${entry.step}</span>
          <span>${entry.latency_ms} ms</span>
        </div>
        <div class="trace-model">${entry.model}</div>
        <div class="trace-summary">${entry.summary}</div>
      `;
      listEl.appendChild(div);
    });
  }

  function renderTasteMeter(tm, uncertainty) {
    const axes = ["setting", "personality", "visual", "voice", "music"];
    axes.forEach((ax) => {
      const val = Math.round(((tm && tm[ax]) || 0.15) * 100);
      const valEl = document.getElementById(`tm-${ax}-val`);
      const barEl = document.getElementById(`tm-${ax}-bar`);
      if (valEl) valEl.textContent = `${val}%`;
      if (barEl) barEl.style.width = `${Math.min(100, Math.max(8, val))}%`;
    });
    const uncEl = document.getElementById("uncertainty-readout");
    if (uncEl && typeof uncertainty === "number") {
      const conf = Math.round((1 - uncertainty) * 100);
      uncEl.textContent = `Signal Confidence: ${conf}%`;
    }
  }

  function renderQuestionView(state) {
    const q = state.current_question;
    if (!q) return;

    const turnNum = String(state.turn_number || 1).padStart(2, "0");
    const maxNum = String(state.max_turns || maxTurnsMode).padStart(2, "0");
    questionProgressLabel.textContent = `QUESTION ${turnNum} / ${maxNum}`;
    questionAxisTag.textContent = (q.axis || "visual").toUpperCase();
    questionHeadline.textContent = q.question;

    // Safety notice check
    if (state.safety_notice && state.safety_notice.allowed === false) {
      safetyBanner.classList.remove("hidden");
      safetyReasonText.textContent = state.safety_notice.reason;
      safetyAltText.textContent = state.safety_notice.safe_alternative_suggestion || "";
    } else {
      safetyBanner.classList.add("hidden");
    }

    // This or That visual comparison
    if (q.ui_mode === "this_or_that" && state.assets && state.assets.option_a_url) {
      thisOrThatBox.classList.remove("hidden");
      visualImgA.src = state.assets.option_a_url;
      visualImgB.src = state.assets.option_b_url;
      visualLabelA.textContent = q.option_a_label || (q.options && q.options[0]) || "Option A";
      visualLabelB.textContent = q.option_b_label || (q.options && q.options[1]) || "Option B";
    } else {
      thisOrThatBox.classList.add("hidden");
    }

    // Render 2-4 choice buttons (including "No preference")
    optionsList.innerHTML = "";
    const opts = (q.options && q.options.length) ? q.options.slice(0, 4) : [
      "Yes — lean into this direction",
      "No — take the opposite angle",
      "No preference — surprise me",
    ];
    opts.forEach((optText, idx) => {
      const btn = document.createElement("button");
      btn.className = "option-btn";
      btn.innerHTML = `
        <span class="option-key">${idx + 1}</span>
        <span>${optText}</span>
      `;
      btn.addEventListener("click", () => sendAnswer(optText));
      optionsList.appendChild(btn);
    });

    renderTasteMeter(state.taste_meter, q.uncertainty_remaining);
  }

  function setBadge(el, verObj) {
    if (!el) return;
    if (!verObj) {
      el.className = "badge badge-pending";
      el.textContent = "PENDING";
      return;
    }
    if (verObj.passed) {
      el.className = "badge badge-pass";
      el.textContent = `PASS (R${verObj.round_num || 1})`;
    } else {
      el.className = "badge badge-warn";
      el.textContent = `UNVERIFIED (R${verObj.round_num || 1})`;
    }
  }

  function renderStudioView(state) {
    const spec = state.spec || {};
    document.getElementById("spec-name").textContent = spec.name || "Synthesizing Companion...";
    document.getElementById("spec-tagline").textContent = (spec.tagline || "LATE-NIGHT COMPANION").toUpperCase();
    document.getElementById("spec-age-badge").textContent = `ADULT (${(spec.apparent_age || "mid 20s").toUpperCase()}) // ORIGINAL IP`;
    document.getElementById("spec-summary-text").textContent = spec.personality_summary || "";
    document.getElementById("spec-setting-text").textContent = spec.setting_description || "";
    document.getElementById("studio-stage-text").textContent = state.current_stage || "";
    document.getElementById("studio-session-id-label").textContent = `SESSION: ${state.session_id}`;

    // Provenance chips
    const provList = document.getElementById("provenance-list");
    provList.innerHTML = "";
    (spec.provenance || []).forEach((p) => {
      const div = document.createElement("div");
      div.className = "provenance-item";
      const qs = (p.source_questions || []).join(", ");
      div.innerHTML = `
        <span>${p.trait}</span>
        <span class="source-chip">because ${qs || "Q1"}</span>
      `;
      provList.appendChild(div);
    });

    // Loop 1: Sheet
    const sheetVer = state.verification && state.verification.sheet;
    setBadge(document.getElementById("badge-loop-sheet"), sheetVer);
    const sheetImg = document.getElementById("studio-sheet-img");
    if (state.assets && state.assets.sheet_url) {
      sheetImg.src = state.assets.sheet_url;
    }
    if (sheetVer) {
      document.getElementById("sheet-metrics-line").textContent =
        `Matched ${sheetVer.matched_count}/${sheetVer.total_traits} traits | 3-view layout: ${sheetVer.three_views_present ? "Yes" : "No"}`;
      const grid = document.getElementById("sheet-traits-grid");
      grid.innerHTML = "";
      (sheetVer.trait_checks || []).forEach((tc) => {
        const row = document.createElement("div");
        row.className = "trait-check-row";
        row.innerHTML = `
          <span class="trait-dot ${tc.present ? "ok" : "miss"}"></span>
          <span>${tc.trait}</span>
        `;
        grid.appendChild(row);
      });
    }

    // Loop 2: Voice
    const djVer = state.verification && state.verification.voice_dj;
    const asmrVer = state.verification && state.verification.voice_asmr;
    setBadge(document.getElementById("badge-loop-voice"), djVer);
    document.getElementById("dj-script-text").textContent = `"${spec.dj_intro_script || ""}"`;
    document.getElementById("asmr-script-text").textContent = `"${spec.asmr_whisper_script || ""}"`;
    if (djVer) {
      document.getElementById("dj-verify-line").textContent =
        `ASR word overlap: ${Math.round(djVer.word_overlap_ratio * 100)}% | Naturalness: ${djVer.naturalness_score}/5 | Persona: ${djVer.persona_match_score}/5`;
    }
    if (asmrVer) {
      document.getElementById("asmr-verify-line").textContent =
        `ASR word overlap: ${Math.round(asmrVer.word_overlap_ratio * 100)}% | Naturalness: ${asmrVer.naturalness_score}/5 | Persona: ${asmrVer.persona_match_score}/5`;
    }
    if (state.assets && state.assets.dj_audio_url) {
      const djEl = document.getElementById("studio-dj-audio");
      if (djEl.getAttribute("data-src") !== state.assets.dj_audio_url) {
        djEl.src = state.assets.dj_audio_url;
        djEl.setAttribute("data-src", state.assets.dj_audio_url);
      }
    }
    if (state.assets && state.assets.asmr_audio_url) {
      const asmrEl = document.getElementById("studio-asmr-audio");
      if (asmrEl.getAttribute("data-src") !== state.assets.asmr_audio_url) {
        asmrEl.src = state.assets.asmr_audio_url;
        asmrEl.setAttribute("data-src", state.assets.asmr_audio_url);
      }
    }

    // Loop 3: Music
    const musVer = state.verification && state.verification.music;
    setBadge(document.getElementById("badge-loop-music"), musVer);
    document.getElementById("music-spec-line").textContent =
      `Target: ${spec.music_genre || "Lo-fi"} | ${spec.music_bpm || 74} BPM | Key: ${spec.music_key || "F minor"}`;
    if (musVer) {
      document.getElementById("music-critique-text").textContent = musVer.critique || "";
      document.getElementById("music-verify-line").textContent =
        `Instrumental: ${musVer.is_instrumental ? "Yes (No Vocals)" : "No"} | Est. BPM: ${musVer.estimated_bpm} | Mood Match: ${musVer.mood_match_score}/5`;
    }
    if (state.assets && state.assets.music_audio_url) {
      const musEl = document.getElementById("studio-music-audio");
      if (musEl.getAttribute("data-src") !== state.assets.music_audio_url) {
        musEl.src = state.assets.music_audio_url;
        musEl.setAttribute("data-src", state.assets.music_audio_url);
      }
    }

    // Loop 4: Video
    const vidVer = state.verification && state.verification.video;
    setBadge(document.getElementById("badge-loop-video"), vidVer);
    if (vidVer) {
      document.getElementById("video-metrics-line").textContent =
        `Character Consistency: ${vidVer.character_consistency_score}/5 | Motion Quality: ${vidVer.motion_quality_score}/5 | Distortion-Free: ${vidVer.distortion_free ? "Yes" : "No"}`;
      document.getElementById("video-observations-text").textContent = vidVer.observations || "";
    }
    if (state.assets && state.assets.video_url) {
      const vEl = document.getElementById("studio-video-preview");
      if (vEl.getAttribute("data-src") !== state.assets.video_url) {
        vEl.src = state.assets.video_url;
        vEl.setAttribute("data-src", state.assets.video_url);
      }
    }
  }

  function renderFocusView(state) {
    const spec = state.spec || {};
    const name = spec.name || "Sora";
    document.getElementById("focus-tagline").textContent = (spec.tagline || "01:30 AM BROADCAST BOOTH").toUpperCase();
    document.getElementById("focus-title").textContent = `Work with ${name}`;
    document.getElementById("focus-music-pill").textContent =
      `${spec.music_bpm || 74} BPM // ${(spec.music_genre || "LO-FI JAZZ").toUpperCase()}`;
    document.getElementById("focus-subtitle-box").textContent = `"${spec.dj_intro_script || ""}"`;

    const stageVid = document.getElementById("focus-stage-video");
    if (state.assets && state.assets.video_url) {
      if (stageVid.getAttribute("data-src") !== state.assets.video_url) {
        stageVid.src = state.assets.video_url;
        stageVid.setAttribute("data-src", state.assets.video_url);
        stageVid.play().catch(() => {});
      }
    }

    if (state.assets) {
      if (state.assets.dj_audio_url) djPlayer.src = state.assets.dj_audio_url;
      if (state.assets.asmr_audio_url) asmrPlayer.src = state.assets.asmr_audio_url;
      if (state.assets.music_audio_url) bgmPlayer.src = state.assets.music_audio_url;

      const mp4Btn = document.getElementById("download-mp4-btn");
      if (state.assets.study_mp4_url) {
        mp4Btn.href = `${state.assets.study_mp4_url.split("?")[0]}?download=1`;
      }
      const kitBtn = document.getElementById("download-kit-btn");
      if (state.assets.kit_zip_url) {
        kitBtn.href = `${state.assets.kit_zip_url.split("?")[0]}?download=1`;
      }
    }
  }

  function syncState(state) {
    currentSession = state;
    renderTrace(state.trace || []);

    const path = window.location.pathname;
    if (path.startsWith("/study/")) {
      renderStudioView(state);
      renderFocusView(state);
      showView("focus");
      return;
    }

    if (state.status === "questioning") {
      renderQuestionView(state);
      showView("question");
    } else if (state.status === "ready_for_spec") {
      showView("studio");
      triggerFullPipeline(state.session_id);
    } else {
      renderStudioView(state);
      renderFocusView(state);
      if (path.startsWith("/demo/")) {
        showView("studio");
      }
    }
  }

  async function startNewSession() {
    stopPolling();
    questionHeadline.textContent = "Tuning the late-night broadcast frequency...";
    optionsList.innerHTML = "";
    showView("question");
    const res = await fetch(`/api/session/start?max_turns=${maxTurnsMode}`, { method: "POST" });
    const state = await res.json();
    window.history.pushState({}, "", "/");
    syncState(state);
  }

  async function sendAnswer(answerText, freeText = null) {
    if (!currentSession) return;
    Array.from(optionsList.querySelectorAll("button")).forEach((b) => (b.disabled = true));
    questionHeadline.textContent = "Listening to your preference...";

    const res = await fetch(`/api/session/${currentSession.session_id}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer: answerText, free_text: freeText }),
    });
    const state = await res.json();
    customAnswerInput.value = "";
    syncState(state);
  }

  async function triggerFullPipeline(sessionId) {
    showView("studio");
    await fetch(`/api/session/${sessionId}/run-pipeline`, { method: "POST" });
    startPolling(sessionId);
  }

  function startPolling(sessionId) {
    stopPolling();
    pollInterval = setInterval(async () => {
      const res = await fetch(`/api/session/${sessionId}`);
      if (!res.ok) return;
      const state = await res.json();
      currentSession = state;
      renderTrace(state.trace || []);
      renderStudioView(state);
      renderFocusView(state);
      if (state.status === "completed") {
        stopPolling();
      }
    }, 2000);
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  }

  // Pomodoro Timer Logic
  function formatTime(sec) {
    const m = String(Math.floor(sec / 60)).padStart(2, "0");
    const s = String(sec % 60).padStart(2, "0");
    return `${m}:${s}`;
  }

  function togglePomodoro() {
    const btn = document.getElementById("timer-start-btn");
    const digits = document.getElementById("pomodoro-digits");
    if (timerRunning) {
      timerRunning = false;
      clearInterval(timerTick);
      btn.textContent = "Resume Focus Session";
      bgmPlayer.pause();
      document.getElementById("toggle-bgm-btn").textContent = "Loop Instrumental: Off";
      return;
    }
    timerRunning = true;
    btn.textContent = "Pause Session";
    // Play DJ intro once then start BGM loop
    if (timerSeconds === 25 * 60 && djPlayer.src) {
      bgmPlayer.volume = 0.25;
      bgmPlayer.play().catch(() => {});
      djPlayer.play().catch(() => {});
      djPlayer.onended = () => {
        bgmPlayer.volume = 0.6;
      };
    } else if (bgmPlayer.src) {
      bgmPlayer.volume = 0.6;
      bgmPlayer.play().catch(() => {});
    }
    document.getElementById("toggle-bgm-btn").textContent = "Loop Instrumental: On";

    timerTick = setInterval(() => {
      if (timerSeconds > 0) {
        timerSeconds -= 1;
        digits.textContent = formatTime(timerSeconds);
      } else {
        clearInterval(timerTick);
        timerRunning = false;
        btn.textContent = "Session Complete";
      }
    }, 1000);
  }

  // Event Listeners
  modeToggleBtn.addEventListener("click", () => {
    maxTurnsMode = maxTurnsMode === 6 ? 10 : 6;
    modeToggleBtn.textContent = maxTurnsMode === 6 ? "Mode: 6Q Quick" : "Mode: 10Q Full";
  });

  newSessionBtn.addEventListener("click", () => startNewSession());
  brandHomeBtn.addEventListener("click", () => startNewSession());

  traceToggleBtn.addEventListener("click", () => {
    traceDrawer.classList.toggle("hidden");
    workspaceRoot.classList.toggle("trace-Collapsed");
  });

  visualCardA.addEventListener("click", () => {
    const label = visualLabelA.textContent || "Option A";
    sendAnswer(`Option A: ${label}`);
  });
  visualCardB.addEventListener("click", () => {
    const label = visualLabelB.textContent || "Option B";
    sendAnswer(`Option B: ${label}`);
  });

  customAnswerSubmit.addEventListener("click", () => {
    const txt = customAnswerInput.value.trim();
    if (txt) sendAnswer(txt);
  });
  customAnswerInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const txt = customAnswerInput.value.trim();
      if (txt) sendAnswer(txt);
    }
  });

  // Keyboard shortcuts 1-4 during Question View
  window.addEventListener("keydown", (e) => {
    if (viewQuestion.classList.contains("hidden")) return;
    if (document.activeElement === customAnswerInput) return;
    const idx = parseInt(e.key, 10) - 1;
    if (idx >= 0 && idx < 4) {
      const btns = optionsList.querySelectorAll("button");
      if (btns[idx] && !btns[idx].disabled) {
        btns[idx].click();
      }
    }
  });

  // Studio Individual Loop Buttons
  document.getElementById("run-all-pipeline-btn").addEventListener("click", () => {
    if (currentSession) triggerFullPipeline(currentSession.session_id);
  });

  document.getElementById("btn-verify-sheet").addEventListener("click", async () => {
    if (!currentSession) return;
    document.getElementById("studio-stage-text").textContent = "Running Loop 01: Character Sheet generation & Argon verification...";
    const res = await fetch(`/api/session/${currentSession.session_id}/verify-sheet`, { method: "POST" });
    syncState(await res.json());
  });

  document.getElementById("btn-verify-voice").addEventListener("click", async () => {
    if (!currentSession) return;
    document.getElementById("studio-stage-text").textContent = "Running Loop 02: Custom TTS voice design + ASR & Flash verification...";
    const res = await fetch(`/api/session/${currentSession.session_id}/verify-voice`, { method: "POST" });
    syncState(await res.json());
  });

  document.getElementById("btn-verify-music").addEventListener("click", async () => {
    if (!currentSession) return;
    document.getElementById("studio-stage-text").textContent = "Running Loop 03: Lyria 30s original music + Flash verification...";
    const res = await fetch(`/api/session/${currentSession.session_id}/verify-music`, { method: "POST" });
    syncState(await res.json());
  });

  document.getElementById("btn-verify-video").addEventListener("click", async () => {
    if (!currentSession) return;
    document.getElementById("studio-stage-text").textContent = "Running Loop 04: Omni video generation + Argon video verification...";
    const res = await fetch(`/api/session/${currentSession.session_id}/verify-video`, { method: "POST" });
    syncState(await res.json());
  });

  document.getElementById("enter-focus-room-btn").addEventListener("click", () => {
    if (!currentSession) return;
    window.history.pushState({}, "", `/study/${currentSession.session_id}`);
    renderFocusView(currentSession);
    showView("focus");
  });

  document.getElementById("back-to-studio-btn").addEventListener("click", () => {
    if (!currentSession) return;
    window.history.pushState({}, "", `/demo/${currentSession.session_id}`);
    renderStudioView(currentSession);
    showView("studio");
  });

  // Focus Room Deck Controls
  document.getElementById("timer-start-btn").addEventListener("click", togglePomodoro);
  document.getElementById("timer-reset-btn").addEventListener("click", () => {
    clearInterval(timerTick);
    timerRunning = false;
    timerSeconds = 25 * 60;
    document.getElementById("pomodoro-digits").textContent = "25:00";
    document.getElementById("timer-start-btn").textContent = "Start Focus Session";
  });

  document.getElementById("play-dj-btn").addEventListener("click", () => {
    if (!currentSession || !currentSession.spec) return;
    document.getElementById("focus-subtitle-box").textContent = `"${currentSession.spec.dj_intro_script}"`;
    bgmPlayer.volume = 0.25;
    djPlayer.currentTime = 0;
    djPlayer.play().catch(() => {});
    djPlayer.onended = () => {
      bgmPlayer.volume = 0.6;
    };
  });

  document.getElementById("play-asmr-btn").addEventListener("click", () => {
    if (!currentSession || !currentSession.spec) return;
    document.getElementById("focus-subtitle-box").textContent = `"${currentSession.spec.asmr_whisper_script}"`;
    bgmPlayer.volume = 0.2;
    asmrPlayer.currentTime = 0;
    asmrPlayer.play().catch(() => {});
    asmrPlayer.onended = () => {
      bgmPlayer.volume = 0.6;
    };
  });

  document.getElementById("toggle-bgm-btn").addEventListener("click", (e) => {
    if (bgmPlayer.paused) {
      bgmPlayer.play().catch(() => {});
      e.target.textContent = "Loop Instrumental: On";
    } else {
      bgmPlayer.pause();
      e.target.textContent = "Loop Instrumental: Off";
    }
  });

  // Initial Route Dispatch
  async function init() {
    const path = window.location.pathname;
    if (path.startsWith("/demo/") || path.startsWith("/study/")) {
      const parts = path.split("/").filter(Boolean);
      const sid = parts[1] || "default";
      const res = await fetch(`/api/session/${sid}`);
      if (res.ok) {
        const state = await res.json();
        syncState(state);
        return;
      }
    }
    await startNewSession();
  }

  init();
})();
