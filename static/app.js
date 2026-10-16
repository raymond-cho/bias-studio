// Bias Studio — Frontend Controller (Bilingual EN/KO, 3 Survey Modes, 16fps/24fps Live Stage, Persona Agent, Marketplace)
(() => {
  let currentSession = null;
  let surveyMode = "quick"; // "quick" (6Q), "general" (10Q), "bias" (20Q)
  let maxTurnsMode = 6;
  let currentLang = "en";
  let pollInterval = null;
  let pendingProposal = null;

  // Connected Google Workspace / Participant Account (persisted in localStorage)
  let googleUser = {
    name: localStorage.getItem("bias_google_name") || "Raymond Cho",
    email: localStorage.getItem("bias_google_email") || "raymond.cho@google-hackathon.kr",
    connected: Boolean(localStorage.getItem("bias_google_email")),
  };

  // Pomodoro state
  let timerSeconds = 25 * 60;
  let timerRunning = false;
  let timerTick = null;

  // Audio players for Focus Room & Marketplace
  const djPlayer = new Audio();
  const asmrPlayer = new Audio();
  const chatVoicePlayer = new Audio();
  const bgmPlayer = new Audio();
  bgmPlayer.loop = true;
  bgmPlayer.volume = 0.55;

  // Bilingual UI dictionary
  const I18N = {
    en: {
      nav_discovery: "Discovery & Webtoon",
      nav_studio: "Verification Rack",
      nav_focus: "Study Room",
      nav_market: "Marketplace × Minihompy",
      nav_about: "Architecture",
      btn_new_discovery: "New Discovery",
      btn_preverified: "Pre-Verified (/demo/default)",
      hero_enter_live: "Enter Live Study Room (/study/default)",
      hero_toggle_roster: "Hide Showcase",
      sm_quick_title: "Quick Mode (6Q)",
      sm_quick_desc: "2–3 choices · ~30s fast discovery",
      sm_general_title: "General Mode (10Q)",
      sm_general_desc: "3–4 choices · balanced styling",
      sm_bias_title: "Bias Master Mode (20Q)",
      sm_bias_desc: "Up to 5 choices + deep custom prompt",
      btn_send_detail: "Send Detail",
      taste_meter_title: "Taste Discovery Meter (5 Axes)",
      btn_run_pipeline: "Run Full Verified Pipeline",
      btn_enter_focus: "Enter Study Room (STUDY WITH ME)",
      btn_inspect_rack: "Inspect Verification Rack",
      btn_publish_market: "Publish to Marketplace",
      btn_start_focus: "Start Focus Session",
      btn_reset_timer: "Reset 25:00",
      btn_play_dj: "Play DJ Intro",
      btn_play_asmr: "ASMR Check-in Whisper",
      chat_panel_title: "LIVE 1:1 PERSONA AGENT // MEMORY & STUDIO DOOR TRANSFORMATION",
      learned_prefs_label: "Learned Listener Taste:",
      btn_chat_send: "Send",
      vocal_panel_title: "SEEU × SUNO CUSTOM VOICE & SOUND ENGINE (3.8-FLASH-TTS + LYRIA-3)",
      hero_headline: "Meet Your Late-Night Webtoon Bias. Live at 16fps+.",
      roster_title: "WEEKLY WEBTOON COMPANION ROSTER (MOVE MOUSE TO INTERACT — CLICK TO LOAD VIBE)",
      custom_input_placeholder: "Or type a custom detail (real people, existing VTubers/Webtoons, and song covers are refused)...",
    },
    ko: {
      nav_discovery: "취향 탐색 & 웹툰 로스터",
      nav_studio: "4대 검증 랙 (Studio)",
      nav_focus: "스터디 룸 (STUDY WITH ME)",
      nav_market: "최애 마켓 × 미니홈피",
      nav_about: "아키텍처 (/about)",
      btn_new_discovery: "새 캐릭터 만들기",
      btn_preverified: "사전 검증 데모 (/demo/default)",
      hero_enter_live: "라이브 스터디룸 바로 입장 (/study/default)",
      hero_toggle_roster: "쇼케이스 접기/펼치기",
      sm_quick_title: "퀵 모드 (6문항 · 30초)",
      sm_quick_desc: "선택지 2~3개 · 핵심 취향 초고속 완성",
      sm_general_title: "제너럴 모드 (10문항 · 1분)",
      sm_general_desc: "선택지 3~4개 · 밸런스형 디테일 설정",
      sm_bias_title: "최애 마스터 모드 (20문항)",
      sm_bias_desc: "선택지 최대 5개 + 자유 프롬프트 정밀 조형",
      btn_send_detail: "디테일 전송",
      taste_meter_title: "실시간 5대 취향 탐색 미터",
      btn_run_pipeline: "전체 멀티모달 검증 파이프라인 실행",
      btn_enter_focus: "스터디룸 입장 (STUDY WITH ME)",
      btn_inspect_rack: "검증 리포트 랙 보기",
      btn_publish_market: "마켓플레이스 × 미니홈피에 등록",
      btn_start_focus: "25분 집중 세션 시작",
      btn_reset_timer: "25:00 초기화",
      btn_play_dj: "DJ 오프닝 보이스 재생",
      btn_play_asmr: "ASMR 속삭임 응원 재생",
      chat_panel_title: "1:1 페르소나 에이전트 채팅 // 취향 학습 & 가상 작업실 문 변신",
      learned_prefs_label: "에이전트가 학습한 내 취향 메모리:",
      btn_chat_send: "전송",
      vocal_panel_title: "시유(SeeU) × Suno 스타일 커스텀 보이스 & 사운드 엔진",
      hero_headline: "나만의 웹툰 최애와 함께하는 16fps+ 심야 작업실",
      roster_title: "요일별 K-웹툰 컴패니언 로스터 (마우스를 움직여 시선/조명 인터랙션 · 클릭 시 무드 즉시 적용)",
      custom_input_placeholder: "원하는 스타일을 자유롭게 적어주세요 (실존 인물·기존 웹툰/버튜버·기존 곡 커버는 안전 게이트가 차단합니다)...",
    },
  };

  // DOM References
  const viewQuestion = document.getElementById("view-question");
  const viewStudio = document.getElementById("view-studio");
  const viewFocus = document.getElementById("view-focus");
  const viewMarketplace = document.getElementById("view-marketplace");
  const viewAbout = document.getElementById("view-about");
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

  function setNavActive(viewName) {
    const map = {
      question: "nav-discovery-btn",
      studio: "nav-studio-btn",
      focus: "nav-focus-btn",
      marketplace: "nav-market-btn",
      about: "nav-about-btn",
    };
    ["nav-discovery-btn", "nav-studio-btn", "nav-focus-btn", "nav-market-btn", "nav-about-btn"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.classList.toggle("active", id === map[viewName]);
    });
  }

  function showView(viewName) {
    viewQuestion.classList.add("hidden");
    viewStudio.classList.add("hidden");
    viewFocus.classList.add("hidden");
    if (viewMarketplace) viewMarketplace.classList.add("hidden");
    if (viewAbout) viewAbout.classList.add("hidden");

    if (viewName === "question") viewQuestion.classList.remove("hidden");
    if (viewName === "studio") viewStudio.classList.remove("hidden");
    if (viewName === "focus") viewFocus.classList.remove("hidden");
    if (viewName === "marketplace" && viewMarketplace) {
      viewMarketplace.classList.remove("hidden");
      loadMarketplace();
    }
    if (viewName === "about" && viewAbout) viewAbout.classList.remove("hidden");
    setNavActive(viewName);
  }

  function applyLanguage(lang) {
    currentLang = lang === "ko" ? "ko" : "en";
    document.getElementById("lang-en-btn").classList.toggle("active", currentLang === "en");
    document.getElementById("lang-ko-btn").classList.toggle("active", currentLang === "ko");

    const dict = I18N[currentLang];
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (dict[key]) el.textContent = dict[key];
    });
    const heroHeadline = document.getElementById("hero-headline-text");
    if (heroHeadline) heroHeadline.textContent = dict.hero_headline;
    const rosterTitle = document.getElementById("roster-title-text");
    if (rosterTitle) rosterTitle.textContent = dict.roster_title;
    if (customAnswerInput) customAnswerInput.placeholder = dict.custom_input_placeholder;
    updateModeButtonLabel();
  }

  function updateModeButtonLabel() {
    const labels = {
      quick: currentLang === "ko" ? "모드: 6문항 퀵" : "Mode: 6Q Quick",
      general: currentLang === "ko" ? "모드: 10문항 제너럴" : "Mode: 10Q General",
      bias: currentLang === "ko" ? "모드: 20문항 최애 마스터" : "Mode: 20Q Bias",
    };
    if (modeToggleBtn) modeToggleBtn.textContent = labels[surveyMode] || "Mode: 6Q Quick";
    ["quick", "general", "bias"].forEach((m) => {
      const btn = document.getElementById(`sm-${m}-btn`);
      if (btn) btn.classList.toggle("active", m === surveyMode);
    });
  }

  function updateGoogleBadge() {
    const labelEl = document.getElementById("google-account-label");
    const marketBadge = document.getElementById("market-account-badge");
    if (googleUser.connected) {
      if (labelEl) labelEl.textContent = `Google: ${googleUser.name}`;
      if (marketBadge) marketBadge.textContent = `CREATOR: ${googleUser.name.toUpperCase()} (${googleUser.email})`;
    } else {
      if (labelEl) labelEl.textContent = currentLang === "ko" ? "Google 계정 연결" : "Connect Google";
      if (marketBadge) marketBadge.textContent = `CREATOR: ${googleUser.name.toUpperCase()}`;
    }
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

    if (state.safety_notice && state.safety_notice.allowed === false) {
      safetyBanner.classList.remove("hidden");
      safetyReasonText.textContent = state.safety_notice.reason;
      safetyAltText.textContent = state.safety_notice.safe_alternative_suggestion || "";
    } else {
      safetyBanner.classList.add("hidden");
    }

    if (q.ui_mode === "this_or_that" && state.assets && state.assets.option_a_url) {
      thisOrThatBox.classList.remove("hidden");
      visualImgA.src = state.assets.option_a_url;
      visualImgB.src = state.assets.option_b_url;
      visualLabelA.textContent = q.option_a_label || (q.options && q.options[0]) || "Option A";
      visualLabelB.textContent = q.option_b_label || (q.options && q.options[1]) || "Option B";
    } else {
      thisOrThatBox.classList.add("hidden");
    }

    optionsList.innerHTML = "";
    const maxChoices = surveyMode === "bias" ? 5 : (surveyMode === "quick" ? 3 : 4);
    const opts = (q.options && q.options.length) ? q.options.slice(0, maxChoices) : [
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

  function renderAgentMemories(state) {
    const chipsBox = document.getElementById("agent-memory-chips");
    if (!chipsBox) return;
    const memories = state.agent_memories || [];
    const qaItems = (state.qa_history || []).slice(-3).map((q) => q.answer);
    const combined = [...memories, ...qaItems].filter(Boolean).slice(-6);
    if (!combined.length) return;
    chipsBox.innerHTML = "";
    combined.forEach((m) => {
      const sp = document.createElement("span");
      sp.className = "source-chip";
      sp.textContent = m.length > 42 ? m.slice(0, 39) + "..." : m;
      chipsBox.appendChild(sp);
    });
    const badge = document.getElementById("agent-memory-count-badge");
    if (badge) badge.textContent = `MEMORY: ${combined.length} TRAITS`;
  }

  function renderFocusView(state) {
    const spec = state.spec || {};
    const name = spec.name || "Sora";
    document.getElementById("focus-tagline").textContent =
      `${(spec.tagline || "01:30 AM BROADCAST BOOTH").toUpperCase()} // 16FPS+ LIVE ANIME ENGINE`;
    document.getElementById("focus-title").textContent = `STUDY WITH ${name.toUpperCase()} - PART 1`;
    document.getElementById("focus-music-pill").textContent =
      `${spec.music_bpm || 74} BPM // ${(spec.music_genre || "LO-FI JAZZ").toUpperCase()}`;
    document.getElementById("focus-subtitle-box").textContent = `"${spec.dj_intro_script || ""}"`;

    const initSender = document.getElementById("chat-init-sender");
    if (initSender) initSender.textContent = `${name} // Studio Companion`;

    const stageVid = document.getElementById("focus-stage-video");
    const stageImg = document.getElementById("focus-stage-image");

    if (state.assets) {
      if (state.assets.video_url && !state.assets.video_fallback_active) {
        stageVid.classList.remove("hidden");
        if (stageImg) stageImg.classList.add("hidden");
        if (stageVid.getAttribute("data-src") !== state.assets.video_url) {
          stageVid.src = state.assets.video_url;
          stageVid.setAttribute("data-src", state.assets.video_url);
          stageVid.play().catch(() => {});
        }
      } else if (state.assets.scene_url && stageImg) {
        stageImg.src = state.assets.scene_url;
        stageImg.classList.remove("hidden");
        stageVid.classList.add("hidden");
      }

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
      const avatarBtn = document.getElementById("export-google-avatar-btn");
      if (avatarBtn && state.session_id) {
        avatarBtn.href = `/api/session/${state.session_id}/google-avatar`;
      }
    }
    renderAgentMemories(state);
  }

  function syncState(state) {
    currentSession = state;
    renderTrace(state.trace || []);

    const path = window.location.pathname;
    if (path === "/about") {
      showView("about");
      return;
    }
    if (path === "/marketplace") {
      showView("marketplace");
      return;
    }
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
    questionHeadline.textContent =
      currentLang === "ko" ? "심야 라디오 주파수를 맞추는 중입니다..." : "Tuning the late-night broadcast frequency...";
    optionsList.innerHTML = "";
    showView("question");
    const res = await fetch(
      `/api/session/start?max_turns=${maxTurnsMode}&survey_mode=${surveyMode}&lang=${currentLang}`,
      { method: "POST" }
    );
    const state = await res.json();
    window.history.pushState({}, "", "/");
    syncState(state);
  }

  async function sendAnswer(answerText, freeText = null) {
    if (!currentSession) return;
    Array.from(optionsList.querySelectorAll("button")).forEach((b) => (b.disabled = true));
    questionHeadline.textContent =
      currentLang === "ko" ? "답변을 바탕으로 다음 질문을 준비하고 있습니다..." : "Listening to your preference...";

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

  // -------------------------------------------------------------------------
  // 24fps (>=12fps Anime Standard) Live Stage Canvas + TTS Lip-Sync Aura
  // -------------------------------------------------------------------------
  function initStage24FpsCanvas() {
    const canvas = document.getElementById("stage-fx-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const rainDrops = Array.from({ length: 34 }, (_, i) => ({
      x: (i * 41) % 1280,
      y: (i * 67) % 720,
      len: 26 + (i % 14),
      speed: 14 + (i % 7),
    }));

    let lastFrameTime = 0;
    const frameInterval = 1000 / 24; // 24fps smooth anime standard (>12fps)

    function isAnyVoiceSpeaking() {
      return (
        (!djPlayer.paused && djPlayer.currentTime > 0) ||
        (!asmrPlayer.paused && asmrPlayer.currentTime > 0) ||
        (!chatVoicePlayer.paused && chatVoicePlayer.currentTime > 0)
      );
    }

    function animateStage(now) {
      requestAnimationFrame(animateStage);
      if (now - lastFrameTime < frameInterval) return;
      lastFrameTime = now;

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const t = now * 0.001;

      // 1. 24fps Rain Streaks & Warm Lamp Dust Motes
      ctx.strokeStyle = "rgba(127, 179, 213, 0.22)";
      ctx.lineWidth = 1.2;
      rainDrops.forEach((d) => {
        ctx.beginPath();
        ctx.moveTo(d.x, d.y);
        ctx.lineTo(d.x - 7, d.y + d.len);
        ctx.stroke();
        d.x = (d.x - 4 + 1280) % 1280;
        d.y = (d.y + d.speed) % 720;
      });

      // Warm 2700K lamp breathing glow in upper-right desk zone
      const lampRadius = 150 + 18 * Math.sin(t * 2.1);
      const grad = ctx.createRadialGradient(980, 220, 10, 980, 220, lampRadius);
      grad.addColorStop(0, "rgba(232, 176, 75, 0.16)");
      grad.addColorStop(1, "rgba(232, 176, 75, 0)");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(980, 220, lampRadius, 0, Math.PI * 2);
      ctx.fill();

      // 2. Subtle 16-24fps Breathing Micro-Motion on Stage Video/Image
      const stageVid = document.getElementById("focus-stage-video");
      const stageImg = document.getElementById("focus-stage-image");
      const speaking = isAnyVoiceSpeaking();
      const breathScale = 1.015 + 0.006 * Math.sin(t * 2.2) + (speaking ? 0.006 * Math.sin(t * 14.0) : 0);
      const breathY = 2.5 * Math.sin(t * 2.2);
      if (stageVid && !stageVid.classList.contains("hidden")) {
        stageVid.style.transform = `scale(${breathScale.toFixed(4)}) translateY(${breathY.toFixed(1)}px)`;
      }
      if (stageImg && !stageImg.classList.contains("hidden")) {
        stageImg.style.transform = `scale(${breathScale.toFixed(4)}) translateY(${breathY.toFixed(1)}px)`;
      }

      // 3. Real-Time TTS Voice Lip-Sync Equalizer & Speaking Aura when Character Speaks
      if (speaking) {
        const cx = 640;
        const cy = 615;
        ctx.save();
        // Voice equalizer bars above subtitle box
        for (let i = -14; i <= 14; i++) {
          const barH = 8 + Math.abs(Math.sin(t * 16 + i * 0.55)) * 26;
          ctx.fillStyle = i % 2 === 0 ? "rgba(232, 176, 75, 0.85)" : "rgba(127, 179, 213, 0.85)";
          ctx.fillRect(cx + i * 10 - 3, cy - barH, 5, barH);
        }
        ctx.restore();
      }
    }
    requestAnimationFrame(animateStage);
  }

  // -------------------------------------------------------------------------
  // 3D Mouse-Following Character Interaction & Cursor Lamp
  // -------------------------------------------------------------------------
  function initMouseTracking() {
    const cursorLamp = document.getElementById("cursor-lamp");
    const coordsReadout = document.getElementById("cursor-coords-readout");

    window.addEventListener("mousemove", (e) => {
      if (cursorLamp) {
        cursorLamp.style.left = `${e.clientX}px`;
        cursorLamp.style.top = `${e.clientY}px`;
      }
      if (coordsReadout) {
        const nx = ((e.clientX / window.innerWidth - 0.5) * 2).toFixed(2);
        const ny = ((e.clientY / window.innerHeight - 0.5) * 2).toFixed(2);
        coordsReadout.textContent = `GAZE TRACKING: X=${nx} Y=${ny}`;
      }
    });

    document.querySelectorAll(".tilt-card").forEach((card) => {
      card.addEventListener("mousemove", (e) => {
        const rect = card.getBoundingClientRect();
        const x = (e.clientX - rect.left) / rect.width - 0.5;
        const y = (e.clientY - rect.top) / rect.height - 0.5;
        const rotY = (x * 10).toFixed(2);
        const rotX = (-y * 10).toFixed(2);
        card.style.transform = `perspective(900px) rotateX(${rotX}deg) rotateY(${rotY}deg)`;
      });
      card.addEventListener("mouseleave", () => {
        card.style.transform = "perspective(900px) rotateX(0deg) rotateY(0deg)";
      });
    });

    // Clicking a MON-SUN Webtoon card loads its vibe into the custom input
    document.querySelectorAll(".webtoon-day-card").forEach((card) => {
      card.addEventListener("click", () => {
        document.querySelectorAll(".webtoon-day-card").forEach((c) => c.classList.remove("active-day"));
        card.classList.add("active-day");
        const vibe = card.getAttribute("data-vibe");
        if (vibe && customAnswerInput) {
          customAnswerInput.value = vibe;
          customAnswerInput.focus();
        }
      });
    });
  }

  // -------------------------------------------------------------------------
  // Autonomous Persona Agent Chat + Virtual Studio Door Transformation
  // -------------------------------------------------------------------------
  function appendChatBubble(role, sender, text) {
    const box = document.getElementById("chat-messages-box");
    if (!box) return;
    const div = document.createElement("div");
    div.className = `chat-bubble ${role}`;
    div.innerHTML = `
      <div class="chat-sender">${sender}</div>
      <div class="chat-text">${text}</div>
    `;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  async function executeDoorTransformation(actionType, updatedPrompt, updatedLabel) {
    if (!currentSession) return;
    const doorOverlay = document.getElementById("studio-door-overlay");
    const doorTitle = document.getElementById("door-title-text");
    const doorStatus = document.getElementById("door-status-text");

    const titleMap = {
      change_style: "STUDIO FITTING DOOR CLOSED — CHANGING HAIRSTYLE & OUTFIT",
      change_background: "STUDIO DOOR CLOSED — RE-STAGING WORKSPACE SCENE",
      change_voice: "SOUND LOCK ACTIVE — RE-TUNING CUSTOM VOICE BANK",
      change_music: "BROADCAST BOOTH LOCK — COMPOSING NEW LYRIA LOOP",
    };
    if (doorTitle) doorTitle.textContent = titleMap[actionType] || "STUDIO DOOR CLOSED — TRANSFORMING";
    if (doorStatus) doorStatus.textContent = `${updatedLabel || updatedPrompt} (16fps+ animation sync)...`;
    if (doorOverlay) doorOverlay.classList.add("closed");

    try {
      const res = await fetch(`/api/session/${currentSession.session_id}/transform`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action_type: actionType,
          updated_prompt: updatedPrompt,
          updated_label: updatedLabel,
          lang: currentLang,
        }),
      });
      if (res.ok) {
        const newState = await res.json();
        currentSession = newState;
        renderTrace(newState.trace || []);
        renderStudioView(newState);
        renderFocusView(newState);
        if (actionType === "change_music" && bgmPlayer.src) {
          bgmPlayer.play().catch(() => {});
          document.getElementById("toggle-bgm-btn").textContent = "Loop Instrumental: On";
        }
      }
    } finally {
      setTimeout(() => {
        if (doorOverlay) doorOverlay.classList.remove("closed");
      }, 650);
    }
  }

  async function sendCompanionChat(messageText) {
    if (!currentSession || !messageText.trim()) return;
    const msg = messageText.trim();
    const chatInput = document.getElementById("chat-input");
    if (chatInput) chatInput.value = "";

    appendChatBubble("user", googleUser.name || "Listener", msg);

    const res = await fetch(`/api/session/${currentSession.session_id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg, lang: currentLang }),
    });
    if (!res.ok) return;
    const reply = await res.json();

    const charName = (currentSession.spec && currentSession.spec.name) || "Sora";
    appendChatBubble("assistant", `${charName} // Studio Host`, reply.reply_text || "...");
    document.getElementById("focus-subtitle-box").textContent = `"${reply.reply_text || ""}"`;

    if (reply.audio_url) {
      chatVoicePlayer.src = reply.audio_url;
      bgmPlayer.volume = 0.22;
      chatVoicePlayer.play().catch(() => {});
      chatVoicePlayer.onended = () => {
        bgmPlayer.volume = 0.55;
      };
    }

    if (reply.agent_memories) {
      currentSession.agent_memories = reply.agent_memories;
      renderAgentMemories(currentSession);
    }

    // If user explicitly requested a transformation, close the Virtual Studio Door and transform!
    if (reply.action_type && reply.action_type !== "none" && reply.updated_prompt) {
      await executeDoorTransformation(reply.action_type, reply.updated_prompt, reply.updated_label);
      return;
    }

    // Otherwise check if Persona Agent made a Proactive Reverse-Proposal
    const propCard = document.getElementById("proactive-proposal-card");
    if (
      reply.proactive_suggestion_type &&
      reply.proactive_suggestion_type !== "none" &&
      reply.proactive_suggestion_prompt
    ) {
      pendingProposal = {
        actionType: reply.proactive_suggestion_type,
        prompt: reply.proactive_suggestion_prompt,
        label: reply.proactive_suggestion_label || "Companion Suggestion",
      };
      document.getElementById("proposal-type-label").textContent = reply.proactive_suggestion_type.toUpperCase();
      document.getElementById("proposal-label-text").textContent =
        reply.proactive_suggestion_label || reply.proactive_suggestion_prompt;
      if (propCard) propCard.classList.remove("hidden");
    }
  }

  // -------------------------------------------------------------------------
  // OpenSea × Cyworld Minihompy Marketplace
  // -------------------------------------------------------------------------
  async function loadMarketplace() {
    const grid = document.getElementById("marketplace-grid");
    if (!grid) return;
    const res = await fetch("/api/marketplace");
    if (!res.ok) return;
    const data = await res.json();
    const items = data.items || [];

    grid.innerHTML = "";
    items.forEach((item) => {
      const card = document.createElement("div");
      card.className = "market-card";
      const commentsHtml = (item.ilchon_comments || [])
        .slice(0, 3)
        .map(
          (c) =>
            `<div class="ilchon-row"><strong>${c.author_name} (${c.relation_label}):</strong> ${c.message}</div>`
        )
        .join("");

      card.innerHTML = `
        <div class="market-card-top">
          <span style="color:var(--accent-amber);">${item.edition_badge || "EDITION #01"}</span>
          <span>TODAY ${item.today_visitors || 12} | TOTAL ${item.total_visitors || 120}</span>
        </div>
        <div class="market-img-wrap">
          <img src="${item.scene_url || "/api/session/default/asset/scene.png"}" alt="${item.character_name}" loading="lazy" />
        </div>
        <div class="market-body">
          <div style="display:flex; justify-content:space-between; align-items:baseline;">
            <h3 style="font-family:var(--font-serif); font-size:26px;">${item.character_name}</h3>
            <span class="badge badge-pass">${item.verified_traits || "8/8"} VERIFIED</span>
          </div>
          <div class="metric-line">${item.tagline || ""} · ${item.bgm_title || ""}</div>
          <div class="metric-line" style="color:var(--accent-cool);">Creator: ${item.creator_name} (${item.creator_email})</div>

          <div class="minihompy-box">
            <div style="font-family:var(--font-mono); font-size:11px; color:var(--accent-amber); margin-bottom:4px;">
              CYWORLD MINIHOMPY // ${item.minihompy_title || "Late-Night Room"}
            </div>
            <div style="color:var(--text-primary); margin-bottom:6px;">"${item.status_message || ""}"</div>
            <audio controls preload="none" src="${item.music_audio_url || "/api/session/default/asset/loop.wav"}" style="width:100%; height:28px;"></audio>
            <div class="ilchon-list">${commentsHtml}</div>
            <div style="display:flex; gap:6px; margin-top:8px;">
              <input type="text" class="text-input ilchon-input" placeholder="Leave 1-Chon Pyeong (일촌평 남기기)..." style="padding:5px 8px; font-size:11px;" />
              <button class="btn btn-sm btn-ilchon-send" data-id="${item.item_id}">Post</button>
            </div>
          </div>

          <div style="display:flex; gap:8px; margin-top:auto;">
            <a class="btn btn-amber btn-sm" href="/study/${item.session_id || "default"}" style="flex:1;">Enter Study Room</a>
            <a class="btn btn-sm" href="/api/session/${item.session_id || "default"}/google-avatar" download>Google Avatar PNG</a>
          </div>
        </div>
      `;

      const sendBtn = card.querySelector(".btn-ilchon-send");
      const inp = card.querySelector(".ilchon-input");
      if (sendBtn && inp) {
        sendBtn.addEventListener("click", async () => {
          const msg = inp.value.trim();
          if (!msg) return;
          await fetch(`/api/marketplace/${item.item_id}/comment`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              author_name: googleUser.name,
              relation_label: "일촌 (Studio Friend)",
              message: msg,
            }),
          });
          inp.value = "";
          loadMarketplace();
        });
      }
      grid.appendChild(card);
    });
  }

  async function publishCurrentToMarketplace() {
    const sid = (currentSession && currentSession.session_id) || "default";
    const name = (currentSession && currentSession.spec && currentSession.spec.name) || "Sora";
    const res = await fetch("/api/marketplace/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sid,
        creator_name: googleUser.name,
        creator_email: googleUser.email,
        minihompy_title: `${name}'s 01:30 AM Broadcast Minihompy`,
        status_message: (currentSession && currentSession.spec && currentSession.spec.dj_intro_script) || "Working quietly through the night.",
      }),
    });
    if (res.ok) {
      window.history.pushState({}, "", "/marketplace");
      showView("marketplace");
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
      btn.textContent = currentLang === "ko" ? "집중 세션 이어하기" : "Resume Focus Session";
      bgmPlayer.pause();
      document.getElementById("toggle-bgm-btn").textContent = "Loop Instrumental: Off";
      return;
    }
    timerRunning = true;
    btn.textContent = currentLang === "ko" ? "일시정지" : "Pause Session";
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

  // Event Listeners — Navigation, Language, Survey Modes, Google Connect
  document.getElementById("lang-en-btn").addEventListener("click", () => {
    applyLanguage("en");
    if (currentSession && currentSession.status === "questioning") startNewSession();
  });
  document.getElementById("lang-ko-btn").addEventListener("click", () => {
    applyLanguage("ko");
    if (currentSession && currentSession.status === "questioning") startNewSession();
  });

  document.getElementById("nav-discovery-btn").addEventListener("click", () => {
    window.history.pushState({}, "", "/");
    showView("question");
  });
  document.getElementById("nav-studio-btn").addEventListener("click", () => {
    if (currentSession) renderStudioView(currentSession);
    showView("studio");
  });
  document.getElementById("nav-focus-btn").addEventListener("click", () => {
    if (currentSession) renderFocusView(currentSession);
    showView("focus");
  });
  document.getElementById("nav-market-btn").addEventListener("click", () => {
    window.history.pushState({}, "", "/marketplace");
    showView("marketplace");
  });
  document.getElementById("nav-about-btn").addEventListener("click", () => {
    window.history.pushState({}, "", "/about");
    showView("about");
  });
  const aboutStartBtn = document.getElementById("about-start-btn");
  if (aboutStartBtn) {
    aboutStartBtn.addEventListener("click", () => {
      window.history.pushState({}, "", "/");
      showView("question");
    });
  }

  // Survey Mode Cards
  document.querySelectorAll(".survey-mode-card").forEach((card) => {
    card.addEventListener("click", () => {
      surveyMode = card.getAttribute("data-mode") || "quick";
      maxTurnsMode = parseInt(card.getAttribute("data-turns") || "6", 10);
      updateModeButtonLabel();
      startNewSession();
    });
  });

  modeToggleBtn.addEventListener("click", () => {
    if (surveyMode === "quick") {
      surveyMode = "general";
      maxTurnsMode = 10;
    } else if (surveyMode === "general") {
      surveyMode = "bias";
      maxTurnsMode = 20;
    } else {
      surveyMode = "quick";
      maxTurnsMode = 6;
    }
    updateModeButtonLabel();
    startNewSession();
  });

  // Hero showcase controls
  const heroCollapseBtn = document.getElementById("hero-collapse-btn");
  const heroSplitGrid = document.getElementById("hero-split-grid");
  if (heroCollapseBtn && heroSplitGrid) {
    heroCollapseBtn.addEventListener("click", () => {
      heroSplitGrid.classList.toggle("hidden");
    });
  }
  const heroUnmuteBtn = document.getElementById("hero-unmute-btn");
  const heroLiveVideo = document.getElementById("hero-live-video");
  if (heroUnmuteBtn && heroLiveVideo) {
    heroUnmuteBtn.addEventListener("click", () => {
      heroLiveVideo.muted = !heroLiveVideo.muted;
      heroUnmuteBtn.textContent = heroLiveVideo.muted ? "Unmute Radio" : "Mute Radio";
    });
  }

  // Google Connect Modal
  const googleModal = document.getElementById("google-modal");
  document.getElementById("google-connect-btn").addEventListener("click", () => {
    document.getElementById("google-name-input").value = googleUser.name;
    document.getElementById("google-email-input").value = googleUser.email;
    googleModal.classList.remove("hidden");
  });
  document.getElementById("google-modal-close").addEventListener("click", () => {
    googleModal.classList.add("hidden");
  });
  document.getElementById("google-demo-fill-btn").addEventListener("click", () => {
    document.getElementById("google-name-input").value = "Raymond Cho (PM)";
    document.getElementById("google-email-input").value = "raymond.cho@deepmind-hackathon.kr";
  });
  document.getElementById("google-save-btn").addEventListener("click", () => {
    googleUser.name = document.getElementById("google-name-input").value.trim() || "Raymond Cho";
    googleUser.email = document.getElementById("google-email-input").value.trim() || "raymond.cho@google-hackathon.kr";
    googleUser.connected = true;
    localStorage.setItem("bias_google_name", googleUser.name);
    localStorage.setItem("bias_google_email", googleUser.email);
    updateGoogleBadge();
    googleModal.classList.add("hidden");
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

  // Keyboard shortcuts 1-5 during Question View
  window.addEventListener("keydown", (e) => {
    if (viewQuestion.classList.contains("hidden")) return;
    if (document.activeElement && ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
    const idx = parseInt(e.key, 10) - 1;
    if (idx >= 0 && idx < 5) {
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
    document.getElementById("timer-start-btn").textContent =
      currentLang === "ko" ? "25분 집중 세션 시작" : "Start Focus Session";
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

  // Persona Agent Chat & Transformation Listeners
  document.getElementById("chat-send-btn").addEventListener("click", () => {
    const inp = document.getElementById("chat-input");
    if (inp && inp.value.trim()) sendCompanionChat(inp.value);
  });
  document.getElementById("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.value.trim()) {
      sendCompanionChat(e.target.value);
    }
  });
  document.querySelectorAll("#quick-transform-chips .chip-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const p = btn.getAttribute("data-prompt");
      if (p) sendCompanionChat(p);
    });
  });

  document.getElementById("accept-proposal-btn").addEventListener("click", async () => {
    const propCard = document.getElementById("proactive-proposal-card");
    if (propCard) propCard.classList.add("hidden");
    if (pendingProposal) {
      await executeDoorTransformation(
        pendingProposal.actionType,
        pendingProposal.prompt,
        pendingProposal.label
      );
      pendingProposal = null;
    }
  });
  document.getElementById("dismiss-proposal-btn").addEventListener("click", () => {
    const propCard = document.getElementById("proactive-proposal-card");
    if (propCard) propCard.classList.add("hidden");
    pendingProposal = null;
  });

  // SeeU / Suno Vocal Studio Listener
  document.getElementById("vocal-synthesize-btn").addEventListener("click", async () => {
    if (!currentSession) return;
    const script = document.getElementById("vocal-script-input").value.trim();
    const styleHint = document.getElementById("vocal-style-input").value.trim();
    const musicPrompt = document.getElementById("vocal-music-input").value.trim();
    const statusLine = document.getElementById("vocal-status-line");
    const btn = document.getElementById("vocal-synthesize-btn");
    if (!script) return;

    btn.disabled = true;
    statusLine.textContent = "Synthesizing custom voice bank with gemini-3.8-flash-tts...";
    try {
      const res = await fetch(`/api/session/${currentSession.session_id}/vocal-studio`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          script,
          style_hint: styleHint,
          music_prompt: musicPrompt || null,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        const audioEl = document.getElementById("vocal-custom-audio");
        if (data.custom_voice_url) {
          audioEl.src = data.custom_voice_url;
          audioEl.play().catch(() => {});
          chatVoicePlayer.src = data.custom_voice_url;
        }
        if (data.music_audio_url) {
          bgmPlayer.src = data.music_audio_url;
        }
        statusLine.textContent = "Custom Voice & Sound Synthesized";
      }
    } finally {
      btn.disabled = false;
    }
  });

  // Marketplace Publish Buttons
  document.getElementById("publish-marketplace-btn").addEventListener("click", publishCurrentToMarketplace);
  document.getElementById("market-publish-current-btn").addEventListener("click", publishCurrentToMarketplace);

  // Initial Route Dispatch
  async function init() {
    updateGoogleBadge();
    initMouseTracking();
    initStage24FpsCanvas();

    const path = window.location.pathname;
    if (path === "/about") {
      showView("about");
      return;
    }
    if (path === "/marketplace") {
      showView("marketplace");
      return;
    }
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
