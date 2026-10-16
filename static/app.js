// Bias Studio — Frontend Controller (Bilingual EN/KO, Toss 3-Stage 18Q Survey, Dynamic Piku A/B, Voice STT + Live Chat, Toss Result UI)
(() => {
  let currentSession = null;
  let surveyMode = "staged"; // "staged" (18Q Toss 3-Stage), "general" (10Q), "quick" (6Q)
  let maxTurnsMode = 18;
  let currentLang = "ko";
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
      nav_about_menu: "About",
      nav_how: "How It Works",
      nav_discovery: "Survey",
      nav_studio: "Verification Rack (/demo)",
      nav_focus: "Study Room",
      nav_market: "Gallery & Landmarks",
      nav_about: "Architecture (/about)",
      menu_options_label: "Options & Demos",
      btn_try_now: "Try Now!",
      btn_new_discovery: "New Discovery Session",
      btn_preverified: "Pre-Verified Demo (/demo/default)",
      hero_title_line1: "Your bias. Your lo-fi.",
      hero_title_line2: "Built and verified in 60 seconds.",
      hero_lead:
        "Pick your favorite traits in fast Ideal-Type World Cup rounds (18 questions across 3 Toss-style stages). Gemini 4 Argon pre-builds your character sheet in the background while you finish personality and studio vibe.",
      hero_cta_try: "Try Now! — Start Toss 3-Stage Discovery",
      hero_enter_live: "Open Live Study Room (/study/default)",
      step_1_text: "Pick traits in fast Ideal-Type World Cup rounds",
      step_2_text: "Argon pre-generates & verifies sheet, voice, music & 16fps video",
      step_3_text: "Talk by voice or text beside your 16:9 live companion",
      finder_caption: "Sample companion: Han Sora (8/8 traits verified)",
      link_try_survey: "Start Survey →",
      link_gallery: "Sample Companions & 10 Korean Landmarks →",
      link_demo: "Verification Rack →",
      link_about: "Architecture →",
      btn_back_landing: "← Back to Overview",
      sm_quick_title: "Quick (6Q)",
      sm_quick_desc: "Fast preview",
      sm_general_title: "General (10Q)",
      sm_general_desc: "Design concept",
      sm_bias_title: "Toss 3-Stage (18Q)",
      sm_bias_desc: "10 Design → Pre-gen → 8 Persona",
      btn_send_detail: "Send Detail",
      taste_meter_title: "Taste Discovery Meter (5 Axes)",
      btn_run_pipeline: "Run Full Verified Pipeline",
      btn_enter_focus: "Enter Study Room (STUDY WITH ME)",
      btn_inspect_rack: "Inspect Verification Rack",
      btn_publish_market: "Add to Gallery",
      btn_start_focus: "Start 25m Focus",
      btn_reset_timer: "Reset",
      btn_play_dj: "DJ Intro",
      btn_play_asmr: "ASMR Whisper",
      chat_panel_title: "LIVE 1:1 VOICE & CHAT // COMPANION REPLIES IMMEDIATELY",
      learned_prefs_label: "Learned Listener Taste:",
      btn_chat_send: "Send",
      vocal_panel_title: "CUSTOM VOICE & SOUND ENGINE (3.8-FLASH-TTS + LYRIA-3)",
      roster_title: "WEEKLY COMPANION ROSTER (CLICK TO LOAD VIBE)",
      custom_input_placeholder: "Or type a custom detail (real people, existing characters, and song covers are refused)...",
    },
    ko: {
      nav_about_menu: "서비스 소개",
      nav_how: "사용 방법 (3단계)",
      nav_discovery: "취향 설문",
      nav_studio: "4대 검증 랙 (/demo)",
      nav_focus: "스터디 룸",
      nav_market: "갤러리 & 한국 야경",
      nav_about: "아키텍처 (/about)",
      menu_options_label: "옵션 & 바로가기",
      btn_try_now: "Try Now! (시작하기)",
      btn_new_discovery: "새 캐릭터 만들기",
      btn_preverified: "사전 검증 데모 (/demo/default)",
      hero_title_line1: "나만의 최애. 나만의 로파이.",
      hero_title_line2: "이상형 월드컵으로 완성하는 심야 작업실.",
      hero_lead:
        "토스처럼 매끄러운 3단계(외형 10문항 → 백그라운드 캐릭터 생성 → 성격 3문항 → 말투·자세·배경 5문항) 설문으로 나만의 2D 최애, 라디오 보이스, 30초 로파이 루프, 16fps 애니메이션 작업실을 완성하세요.",
      hero_cta_try: "Try Now! — 토스식 3단계 이상형 월드컵 시작하기",
      hero_enter_live: "라이브 스터디룸 바로 입장 (/study/default)",
      step_1_text: "이상형 월드컵 방식의 빠른 취향 선택",
      step_2_text: "5~6개 프롬프트 배치 합성 & 백그라운드 사전 생성",
      step_3_text: "영상 옆 실시간 음성/채팅 대화 & 집중 타이머",
      finder_caption: "샘플 컴패니언: 한소라 (8/8 시각 특성 검증 완료)",
      link_try_survey: "취향 설문 시작 →",
      link_gallery: "요일별 캐릭터 & 한국 10대 명소 갤러리 →",
      link_demo: "4대 검증 랙 보기 →",
      link_about: "시스템 아키텍처 →",
      btn_back_landing: "← 소개 화면으로 돌아가기",
      sm_quick_title: "퀵 모드 (6문항)",
      sm_quick_desc: "빠른 핵심 테스트",
      sm_general_title: "디자인 집중 (10문항)",
      sm_general_desc: "외형 컨셉 10문항",
      sm_bias_title: "토스 3단계 위저드 (18문항 · 추천)",
      sm_bias_desc: "외형10 → 사전생성 → 성격3 → 말투·배경5",
      btn_send_detail: "디테일 전송",
      taste_meter_title: "실시간 5대 취향 탐색 미터",
      btn_run_pipeline: "전체 멀티모달 검증 파이프라인 실행",
      btn_enter_focus: "스터디룸 입장 (STUDY WITH ME)",
      btn_inspect_rack: "검증 리포트 랙 보기",
      btn_publish_market: "갤러리에 등록",
      btn_start_focus: "25분 집중 시작",
      btn_reset_timer: "초기화",
      btn_play_dj: "DJ 오프닝",
      btn_play_asmr: "ASMR 속삭임",
      chat_panel_title: "실시간 1:1 보이스 & 채팅 // 말을 걸면 바로 인식하고 대답해요",
      learned_prefs_label: "에이전트가 기억한 내 취향:",
      btn_chat_send: "전송",
      vocal_panel_title: "커스텀 보이스 & 사운드 엔진 (3.8-FLASH-TTS + LYRIA-3)",
      roster_title: "요일별 컴패니언 로스터 (클릭 시 무드 즉시 적용)",
      custom_input_placeholder: "원하는 스타일을 자유롭게 적어주세요 (실존 인물·기존 캐릭터·기존 곡 커버는 안전 게이트가 차단합니다)...",
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
  const heroShowcaseEl = document.getElementById("hero-webtoon-showcase");
  const surveyStageEl = document.getElementById("question-survey-stage");

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

  function openLandingStage() {
    if (heroShowcaseEl) heroShowcaseEl.classList.remove("hidden");
    if (surveyStageEl) surveyStageEl.classList.add("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openSurveyStage() {
    if (heroShowcaseEl) heroShowcaseEl.classList.add("hidden");
    if (surveyStageEl) {
      surveyStageEl.classList.remove("hidden");
      surveyStageEl.classList.remove("view-fade-enter");
      void surveyStageEl.offsetWidth;
      surveyStageEl.classList.add("view-fade-enter");
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

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
    const views = [viewQuestion, viewStudio, viewFocus, viewMarketplace, viewAbout].filter(Boolean);
    views.forEach((v) => {
      v.classList.add("hidden");
      v.classList.remove("view-fade-enter");
    });

    let activeEl = null;
    if (viewName === "question") activeEl = viewQuestion;
    if (viewName === "studio") activeEl = viewStudio;
    if (viewName === "focus") activeEl = viewFocus;
    if (viewName === "marketplace" && viewMarketplace) {
      activeEl = viewMarketplace;
      loadMarketplace();
    }
    if (viewName === "about" && viewAbout) activeEl = viewAbout;
    if (activeEl) {
      activeEl.classList.remove("hidden");
      void activeEl.offsetWidth;
      activeEl.classList.add("view-fade-enter");
    }
    setNavActive(viewName);
  }

  function applyLanguage(lang) {
    currentLang = lang === "ko" ? "ko" : "en";
    document.getElementById("lang-en-btn").classList.toggle("active", currentLang === "en");
    document.getElementById("lang-ko-btn").classList.toggle("active", currentLang === "ko");
    const langLabel = document.getElementById("current-lang-label");
    if (langLabel) {
      langLabel.textContent = currentLang === "ko" ? "🌐 한국어 (KO)" : "🌐 English (EN)";
    }

    const dict = I18N[currentLang];
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (dict[key]) el.textContent = dict[key];
    });
    const rosterTitle = document.getElementById("roster-title-text");
    if (rosterTitle) rosterTitle.textContent = dict.roster_title;
    if (customAnswerInput) customAnswerInput.placeholder = dict.custom_input_placeholder;
    updateModeButtonLabel();
  }

  function updateModeButtonLabel() {
    const labels = {
      staged: currentLang === "ko" ? "모드: 18문항 토스 3단계" : "Mode: 18Q Toss 3-Stage",
      general: currentLang === "ko" ? "모드: 10문항 디자인" : "Mode: 10Q Design",
      quick: currentLang === "ko" ? "모드: 6문항 퀵" : "Mode: 6Q Quick",
      bias: currentLang === "ko" ? "모드: 18문항 토스 3단계" : "Mode: 18Q Toss 3-Stage",
    };
    if (modeToggleBtn) modeToggleBtn.textContent = labels[surveyMode] || labels.staged;
    ["staged", "general", "quick", "bias"].forEach((m) => {
      const btn = document.getElementById(`sm-${m}-btn`);
      if (btn) btn.classList.toggle("active", m === surveyMode);
    });
  }

  function updateGoogleBadge() {
    const labelEl = document.getElementById("google-account-label");
    const navLabelEl = document.getElementById("navbar-google-label");
    const focusGoogleBtn = document.getElementById("focus-google-pill-btn");
    const marketBadge = document.getElementById("market-account-badge");
    if (googleUser.connected) {
      if (labelEl) labelEl.textContent = `Google: ${googleUser.name}`;
      if (navLabelEl) navLabelEl.textContent = `${googleUser.name}`;
      if (focusGoogleBtn) focusGoogleBtn.textContent = `✓ Google 연동됨 (${googleUser.name})`;
      if (marketBadge) marketBadge.textContent = `CREATOR: ${googleUser.name.toUpperCase()} (${googleUser.email})`;
    } else {
      if (labelEl) labelEl.textContent = currentLang === "ko" ? "Google 계정 연결" : "Connect Google";
      if (navLabelEl) navLabelEl.textContent = currentLang === "ko" ? "Google 연동" : "Google Sign-In";
      if (focusGoogleBtn) focusGoogleBtn.textContent = "Google 계정 연동";
      if (marketBadge) marketBadge.textContent = `CREATOR: ${googleUser.name.toUpperCase()}`;
    }
  }

  async function syncGoogleAccountWithServer(name, email) {
    googleUser.name = (name || "Raymond Cho").trim();
    googleUser.email = (email || "raymond.cho@google-hackathon.kr").trim();
    googleUser.connected = true;
    localStorage.setItem("bias_google_name", googleUser.name);
    localStorage.setItem("bias_google_email", googleUser.email);
    updateGoogleBadge();
    try {
      await fetch("/api/google/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: googleUser.name,
          email: googleUser.email,
          session_id: (currentSession && currentSession.session_id) || "default",
        }),
      });
    } catch (_) {
      // Non-blocking sync
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

  function setMediaSrcIfChanged(el, newUrl) {
    if (!el || !newUrl) return false;
    if (el.getAttribute("data-src") === newUrl || el.getAttribute("src") === newUrl) {
      return false;
    }
    el.src = newUrl;
    el.setAttribute("data-src", newUrl);
    return true;
  }

  function renderQuestionView(state) {
    const q = state.current_question;
    if (!q) return;

    const turnIdx = Number(state.turn_number || 1);
    const maxTurnsNum = Number(state.max_turns || maxTurnsMode || 18);
    const turnNum = String(turnIdx).padStart(2, "0");
    const maxNum = String(maxTurnsNum).padStart(2, "0");
    questionProgressLabel.textContent = `QUESTION ${turnNum} / ${maxNum}`;
    questionAxisTag.textContent = (q.axis || "visual").toUpperCase();
    questionHeadline.textContent = q.question;

    // Toss linear progress bar
    const tossProgressFill = document.getElementById("toss-survey-progress-fill");
    if (tossProgressFill) {
      const pct = Math.min(100, Math.max(5, Math.round((turnIdx / maxTurnsNum) * 100)));
      tossProgressFill.style.width = `${pct}%`;
    }

    // Toss stage callout banner
    const stageCallout = document.getElementById("toss-stage-callout");
    const stageCalloutText = document.getElementById("toss-stage-callout-text");
    if (stageCallout && stageCalloutText) {
      if (q.stage_intro_banner) {
        stageCalloutText.textContent = q.stage_intro_banner;
        stageCallout.classList.remove("hidden");
      } else if (turnIdx <= 10) {
        stageCalloutText.textContent =
          currentLang === "ko"
            ? `지금부터 캐릭터 디자인 컨셉을 정하고 있어요 (${turnIdx}/10) · 10문항 완료 시 5개씩 프롬프트를 묶어 백그라운드 생성을 시작합니다.`
            : `Stage 1 (${turnIdx}/10): Choosing character design concept. After Q10, we bundle 5-prompt batches & start background generation.`;
      } else if (turnIdx <= 13) {
        stageCalloutText.textContent =
          currentLang === "ko"
            ? `백그라운드에서 캐릭터를 생성하고 있어요 · 기다리는 동안 성격 설정(${turnIdx - 10}/3)을 진행합니다.`
            : `Generating character sheet in background · Setting personality (${turnIdx - 10}/3) while you wait.`;
      } else {
        stageCalloutText.textContent =
          currentLang === "ko"
            ? `성격 설정 완료! 마지막으로 말투, 작업 자세, 작업하는 배경(${turnIdx - 13}/5)을 정하고 있어요.`
            : `Stage 3 (${turnIdx - 13}/5): Finalizing speech tone, desk posture, and studio background.`;
      }
    }

    // Update Characteristic Creation Chapter Banner & Custom Box Label
    const chapterStepPill = document.getElementById("chapter-step-pill");
    const chapterTailoredStatus = document.getElementById("chapter-tailored-status");
    const chapterTitleText = document.getElementById("chapter-title-text");
    const customPromptLabel = document.getElementById("custom-box-prompt-label");
    const chipQ1 = document.getElementById("chip-q1");
    const chipQ2 = document.getElementById("chip-q2");
    const chipQ3 = document.getElementById("chip-q3");
    const chipQ4 = document.getElementById("chip-q4");
    const chipQ5 = document.getElementById("chip-q5");

    const hasDesignPrewarm = Boolean(
      state.batched_prompts &&
        (state.batched_prompts.batch_2_wardrobe_concept || state.batched_prompts.batch_1_silhouette_gaze)
    );
    if (chipQ1) chipQ1.classList.toggle("active-chip", turnIdx >= 1 && turnIdx <= 5);
    if (chipQ2) chipQ2.classList.toggle("active-chip", turnIdx >= 6 && turnIdx <= 10);
    if (chipQ3) chipQ3.classList.toggle("active-chip", hasDesignPrewarm || turnIdx > 10);
    if (chipQ4) chipQ4.classList.toggle("active-chip", turnIdx >= 11 && turnIdx <= 13);
    if (chipQ5) chipQ5.classList.toggle("active-chip", turnIdx >= 14);

    let stepGroup = 1;
    if (turnIdx <= 10) {
      stepGroup = 1;
    } else if (turnIdx >= 11 && turnIdx <= 13) {
      stepGroup = 2;
    } else {
      stepGroup = 3;
    }

    if (stepGroup === 1) {
      if (chapterStepPill) {
        chapterStepPill.textContent =
          currentLang === "ko"
            ? "STAGE 1 OF 3 · 캐릭터 디자인 컨셉 (Q1–Q10)"
            : "STAGE 1 OF 3 · CHARACTER DESIGN CONCEPT (Q1–Q10)";
      }
      if (chapterTitleText) {
        chapterTitleText.textContent =
          currentLang === "ko"
            ? "지금부터 캐릭터 디자인 컨셉을 정해볼게요 (이상형 월드컵 10문항)"
            : "Let's decide your character design concept (10 fast choices)";
      }
      if (customPromptLabel) {
        customPromptLabel.textContent =
          currentLang === "ko"
            ? "상상하는 최애의 외모·헤어·스타일을 자유롭게 적어주세요:"
            : "Describe your favorite bias appearance, hair, or outfit:";
      }
    } else if (stepGroup === 2) {
      if (chapterStepPill) {
        chapterStepPill.textContent =
          currentLang === "ko"
            ? "STAGE 2 OF 3 · 캐릭터 생성 중 & 성격 설정 (Q11–Q13)"
            : "STAGE 2 OF 3 · GENERATING SHEET & PERSONALITY (Q11–Q13)";
      }
      if (chapterTitleText) {
        chapterTitleText.textContent =
          currentLang === "ko"
            ? "캐릭터를 생성하고 있어요 — 기다리는 동안 성격 설정으로 넘어갈게요"
            : "Generating character sheet — let's set personality while waiting";
      }
      if (customPromptLabel) {
        customPromptLabel.textContent =
          currentLang === "ko"
            ? "원하는 최애의 성격이나 텐션이 있다면 직접 적어주세요:"
            : "Describe the personality or vibe you want:";
      }
    } else {
      if (chapterStepPill) {
        chapterStepPill.textContent =
          currentLang === "ko"
            ? "STAGE 3 OF 3 · 말투·자세·작업 배경 (Q14–Q18)"
            : "STAGE 3 OF 3 · SPEECH TONE, POSTURE & BACKGROUND (Q14–Q18)";
      }
      if (chapterTitleText) {
        chapterTitleText.textContent =
          currentLang === "ko"
            ? "이제는 말투, 작업하는 자세, 그리고 작업실 배경을 완성할게요"
            : "Now let's finish speech tone, desk posture, and workspace background";
      }
      if (customPromptLabel) {
        customPromptLabel.textContent =
          currentLang === "ko"
            ? "최애의 말투·자세·원하는 작업실 배경이나 로파이 악기를 적어주세요:"
            : "Describe how your bias talks, sits, or what lo-fi sound plays:";
      }
    }

    if (chapterTailoredStatus) {
      if (turnIdx <= 10) {
        chapterTailoredStatus.textContent =
          currentLang === "ko"
            ? "⚡ Piku 이상형 월드컵 방식 · 5개 단위 배치 프롬프트 합성 대기 중"
            : "⚡ Piku Ideal-Type World Cup · 5-Prompt Batch Synthesis Active";
      } else {
        chapterTailoredStatus.textContent =
          currentLang === "ko"
            ? "🚀 백그라운드에서 캐릭터 시트 사전 생성 중 (Gemini 4 Argon + Nano Banana)"
            : "🚀 Character Sheet Pre-Generating in Background (Argon + Nano Banana)";
      }
    }

    if (state.safety_notice && state.safety_notice.allowed === false) {
      safetyBanner.classList.remove("hidden");
      safetyReasonText.textContent = state.safety_notice.reason;
      safetyAltText.textContent = state.safety_notice.safe_alternative_suggestion || "";
    } else {
      safetyBanner.classList.add("hidden");
    }

    // Dynamic Visual A/B ("This-or-That") Sample Images — never static/repeated!
    const optAUrl = q.option_a_url || (state.assets && state.assets.option_a_url);
    const optBUrl = q.option_b_url || (state.assets && state.assets.option_b_url);
    if (q.ui_mode === "this_or_that" && optAUrl && optBUrl) {
      thisOrThatBox.classList.remove("hidden");
      setMediaSrcIfChanged(visualImgA, optAUrl);
      setMediaSrcIfChanged(visualImgB, optBUrl);
      visualLabelA.textContent = q.option_a_label || (q.options && q.options[0]) || "Option A";
      visualLabelB.textContent = q.option_b_label || (q.options && q.options[1]) || "Option B";
    } else {
      thisOrThatBox.classList.add("hidden");
    }

    optionsList.innerHTML = "";
    const opts =
      q.options && q.options.length
        ? q.options.slice(0, 4)
        : [
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
      btn.addEventListener("click", () => {
        btn.classList.add("selected-pulse");
        sendAnswer(optText);
      });
      optionsList.appendChild(btn);
    });

    renderTasteMeter(state.taste_meter, q.uncertainty_remaining);
  }

  function showTossInterstitial(interstitial, batchedPrompts) {
    return new Promise((resolve) => {
      const card = document.getElementById("toss-interstitial-card");
      const focalCard = document.getElementById("question-focal-card");
      const badgeEl = document.getElementById("toss-interstitial-badge");
      const titleEl = document.getElementById("toss-interstitial-title");
      const subEl = document.getElementById("toss-interstitial-sub");
      const barEl = document.getElementById("toss-interstitial-bar");
      const chipsEl = document.getElementById("toss-batch-chips");
      const skipBtn = document.getElementById("toss-interstitial-skip-btn");

      if (!card || !interstitial) {
        resolve();
        return;
      }

      if (focalCard) focalCard.classList.add("hidden");
      card.classList.remove("hidden");

      const stageName = interstitial.batch_stage || "batch_q10";
      if (badgeEl) {
        badgeEl.textContent =
          stageName === "batch_q10" || stageName === "design_10"
            ? "TOSS AI BATCH PRE-GENERATION // Q1–Q10 (5+5 PROMPTS BUNDLED)"
            : "TOSS AI PERSONA SYNTHESIS // Q11–Q13 BUNDLED";
      }
      if (titleEl) titleEl.textContent = interstitial.title || "캐릭터를 생성하고 있어요";
      if (subEl) {
        subEl.textContent =
          interstitial.subtitle ||
          "기다리는 동안 다음 작업으로 넘어갈까요? 이제는 성격 설정을 진행할게요!";
      }

      if (chipsEl) {
        chipsEl.innerHTML = "";
        const batches = batchedPrompts || {};
        Object.entries(batches).forEach(([k, v]) => {
          if (!v) return;
          const sp = document.createElement("span");
          sp.className = "source-chip";
          const shortVal = String(v).length > 64 ? String(v).slice(0, 61) + "..." : String(v);
          sp.textContent = `📦 ${k}: ${shortVal}`;
          chipsEl.appendChild(sp);
        });
      }

      const durationMs = Math.max(2000, Math.min(7000, Number(interstitial.duration_sec || 6) * 1000));
      if (barEl) {
        barEl.style.transition = "none";
        barEl.style.width = "4%";
        void barEl.offsetWidth;
        barEl.style.transition = `width ${durationMs}ms linear`;
        barEl.style.width = "100%";
      }

      let finished = false;
      const finish = () => {
        if (finished) return;
        finished = true;
        card.classList.add("hidden");
        if (focalCard) {
          focalCard.classList.remove("hidden", "q-card-exit");
          focalCard.classList.add("q-card-enter");
        }
        resolve();
      };

      const timer = setTimeout(finish, durationMs);
      if (skipBtn) {
        skipBtn.onclick = () => {
          clearTimeout(timer);
          finish();
        };
      }
    });
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

    const buildingTitle = document.getElementById("building-title-text");
    const buildingSub = document.getElementById("building-sub-text");
    const buildingSpinner = document.getElementById("building-spinner");
    if (state.status === "completed") {
      if (buildingTitle) {
        buildingTitle.textContent =
          currentLang === "ko"
            ? "✓ 2.5D 나만의 최애 제작 및 4대 검증 완료!"
            : "✓ 2.5D Companion Ready — All 4 Verification Loops Complete!";
      }
      if (buildingSub) {
        buildingSub.textContent =
          currentLang === "ko"
            ? "오른쪽 상단 'Enter Study Room' 버튼을 눌러 1:1 라이브 스터디룸으로 입장하세요."
            : "Click 'Enter Study Room (STUDY WITH ME)' above to start your 1:1 session.";
      }
      if (buildingSpinner) buildingSpinner.style.display = "none";
    } else {
      if (buildingTitle) {
        buildingTitle.textContent =
          currentLang === "ko"
            ? "만들어지는 중... // 2.5D 최애 캐릭터·보이스·로파이 생성 중"
            : "Building your 2.5D companion... (만들어지는 중...)";
      }
      if (buildingSub) {
        buildingSub.textContent =
          state.current_stage ||
          "Synthesizing character sheet, custom voice bank, 30s Lyria lo-fi loop, and 16fps animation...";
      }
      if (buildingSpinner) buildingSpinner.style.display = "inline-block";
    }

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
      setMediaSrcIfChanged(sheetImg, state.assets.sheet_url);
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
      setMediaSrcIfChanged(document.getElementById("studio-dj-audio"), state.assets.dj_audio_url);
    }
    if (state.assets && state.assets.asmr_audio_url) {
      setMediaSrcIfChanged(document.getElementById("studio-asmr-audio"), state.assets.asmr_audio_url);
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
      setMediaSrcIfChanged(document.getElementById("studio-music-audio"), state.assets.music_audio_url);
    }

    const vidVer = state.verification && state.verification.video;
    setBadge(document.getElementById("badge-loop-video"), vidVer);
    if (vidVer) {
      document.getElementById("video-metrics-line").textContent =
        `Character Consistency: ${vidVer.character_consistency_score}/5 | Motion Quality: ${vidVer.motion_quality_score}/5 | Distortion-Free: ${vidVer.distortion_free ? "Yes" : "No"}`;
      document.getElementById("video-observations-text").textContent = vidVer.observations || "";
    }
    if (state.assets && state.assets.video_url) {
      setMediaSrcIfChanged(document.getElementById("studio-video-preview"), state.assets.video_url);
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

  const EMOTION_LABELS = {
    calm_focus: "😌 차분한 몰입 (Calm Focus)",
    warm_smile: "😊 다정한 미소 (Warm Smile)",
    shy_flutter: "😳 설레는 수줍음 (Shy Flutter)",
    cheering: "🙌 열정 응원 (Cheering)",
    sleepy_night: "🌙 나른한 새벽 (Sleepy Night)",
  };

  function updateAffectionUI(score, bondTitle, delta = 0) {
    const safeScore = Math.max(0, Math.min(100, Number(score || 28)));
    const badgeEl = document.getElementById("bond-level-badge");
    const fillEl = document.getElementById("bond-bar-fill");
    const labelEl = document.getElementById("bond-score-label");
    const popEl = document.getElementById("affection-pop-badge");

    if (badgeEl && bondTitle) badgeEl.textContent = bondTitle;
    if (fillEl) fillEl.style.width = `${safeScore}%`;
    if (labelEl) labelEl.textContent = `❤️ ${safeScore} / 100`;

    if (popEl && delta > 0) {
      popEl.textContent = `+${delta} ❤️`;
      popEl.classList.remove("hidden");
      clearTimeout(popEl._hideTimer);
      popEl._hideTimer = setTimeout(() => {
        popEl.classList.add("hidden");
      }, 2800);
    }
  }

  function updateEmotionUI(emotionKey) {
    const label = EMOTION_LABELS[emotionKey] || EMOTION_LABELS.calm_focus;
    const stagePill = document.getElementById("focus-emotion-pill");
    const callPill = document.getElementById("voice-call-emotion-pill");
    if (stagePill) stagePill.textContent = label;
    if (callPill) callPill.textContent = label;
  }

  function renderFocusView(state) {
    const spec = state.spec || {};
    const name = spec.name || "Sora";
    const sid = state.session_id || "default";
    document.getElementById("focus-tagline").textContent =
      `${(spec.tagline || "01:30 AM BROADCAST BOOTH").toUpperCase()} // 16FPS+ LIVE ANIME ENGINE`;
    document.getElementById("focus-title").textContent = `STUDY WITH ${name.toUpperCase()} - PART 1`;
    document.getElementById("focus-music-pill").textContent =
      `${spec.music_bpm || 74} BPM // ${(spec.music_genre || "LO-FI JAZZ").toUpperCase()}`;
    document.getElementById("focus-subtitle-box").textContent = `"${spec.dj_intro_script || ""}"`;

    // Update Affection / Bond Level & Lorebook Dossier strip
    updateAffectionUI(state.affection_score || 28, state.bond_level_title || "Lv.1 설레는 첫만남", 0);
    updateEmotionUI(state.current_emotion || "calm_focus");

    const mbtiPill = document.getElementById("char-mbti-pill");
    const drinkPill = document.getElementById("char-drink-pill");
    const habitPill = document.getElementById("char-habit-pill");
    if (mbtiPill) mbtiPill.textContent = `MBTI: ${spec.mbti || "INFJ-T"}`;
    if (drinkPill) drinkPill.textContent = `☕ ${spec.signature_drink || "따뜻한 드립커피"}`;
    if (habitPill) habitPill.textContent = `✨ ${spec.secret_habit || "집중할 때 안경테 만지작거리기"}`;

    const initSender = document.getElementById("chat-init-sender");
    if (initSender) initSender.textContent = `${name} // Studio Companion`;
    const initNarration = document.getElementById("chat-init-narration");
    if (initNarration && spec.first_greeting_narration) {
      initNarration.textContent = `*${spec.first_greeting_narration.replace(/^\*|\*$/g, "")}*`;
    }
    const initText = document.getElementById("chat-init-text");
    if (initText && spec.first_greeting_line) {
      initText.textContent = `"${spec.first_greeting_line.replace(/^"|"$/g, "")}"`;
    }

    // Update Voice Call modal header
    const callName = document.getElementById("voice-call-name");
    if (callName) callName.textContent = name;
    const callAvatar = document.getElementById("voice-call-avatar-img");
    if (callAvatar && state.assets && state.assets.scene_url) {
      callAvatar.src = state.assets.scene_url;
    }

    // Update Photocard & Google Avatar links
    ["download-photocard-quick-btn", "download-photocard-btn", "diary-photocard-link"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.href = `/api/session/${sid}/photocard`;
    });

    const stageVid = document.getElementById("focus-stage-video");
    const stageImg = document.getElementById("focus-stage-image");

    if (state.assets) {
      if (state.assets.video_url && !state.assets.video_fallback_active) {
        stageVid.classList.remove("hidden");
        if (stageImg) stageImg.classList.add("hidden");
        if (setMediaSrcIfChanged(stageVid, state.assets.video_url)) {
          stageVid.play().catch(() => {});
        }
      } else if (state.assets.scene_url && stageImg) {
        setMediaSrcIfChanged(stageImg, state.assets.scene_url);
        stageImg.classList.remove("hidden");
        stageVid.classList.add("hidden");
      }

      if (state.assets.dj_audio_url) setMediaSrcIfChanged(djPlayer, state.assets.dj_audio_url);
      if (state.assets.asmr_audio_url) setMediaSrcIfChanged(asmrPlayer, state.assets.asmr_audio_url);
      if (state.assets.music_audio_url) setMediaSrcIfChanged(bgmPlayer, state.assets.music_audio_url);

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
    const interstitialCard = document.getElementById("toss-interstitial-card");
    const focalCard = document.getElementById("question-focal-card");
    if (interstitialCard) interstitialCard.classList.add("hidden");
    if (focalCard) {
      focalCard.classList.remove("hidden", "q-card-exit");
      focalCard.classList.add("q-card-enter");
    }
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

    const focalCard = document.getElementById("question-focal-card");
    if (focalCard) {
      focalCard.classList.remove("q-card-enter");
      focalCard.classList.add("q-card-exit");
    }

    const answerPromise = fetch(`/api/session/${currentSession.session_id}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer: answerText, free_text: freeText }),
    }).then((r) => r.json());

    // Wait briefly so the spring exit animation feels tactile and smooth
    const [state] = await Promise.all([
      answerPromise,
      new Promise((r) => setTimeout(r, 170)),
    ]);

    customAnswerInput.value = "";

    // Trigger non-blocking batched 5-prompt AI pre-generation if scheduled (e.g. after Q10 or Q13)
    if (state.pending_batch_stage && state.session_id) {
      fetch(`/api/session/${state.session_id}/prewarm-batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: state.pending_batch_stage }),
      }).catch(() => {});
    }

    // Show Toss Securities / Toss Bank interstitial ("캐릭터를 생성하고 있어요 — 기다리는 동안 성격 설정으로 넘어갈까요?")
    if (state.last_interstitial && state.status === "questioning") {
      await showTossInterstitial(state.last_interstitial, state.batched_clusters || state.batched_prompts);
    } else if (focalCard) {
      focalCard.classList.remove("q-card-exit");
      void focalCard.offsetWidth;
      focalCard.classList.add("q-card-enter");
    }

    syncState(state);
  }

  async function triggerFullPipeline(sessionId) {
    showView("studio");
    await fetch(`/api/session/${sessionId}/run-pipeline`, { method: "POST" });
    startPolling(sessionId);
  }

  function startPolling(sessionId) {
    stopPolling();
    let lastUpdatedAt = currentSession ? currentSession.updated_at : null;
    let lastStage = currentSession ? currentSession.current_stage : null;
    let lastStatus = currentSession ? currentSession.status : null;

    pollInterval = setInterval(async () => {
      if (document.hidden) return;
      const res = await fetch(`/api/session/${sessionId}`);
      if (!res.ok) return;
      const state = await res.json();
      const changed =
        state.updated_at !== lastUpdatedAt ||
        state.current_stage !== lastStage ||
        state.status !== lastStatus;

      currentSession = state;
      if (changed) {
        lastUpdatedAt = state.updated_at;
        lastStage = state.current_stage;
        lastStatus = state.status;
        renderTrace(state.trace || []);
        renderStudioView(state);
        renderFocusView(state);
      }
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
  // Capped 30fps Live Stage Canvas (Paused when tab hidden) + Voice-Reactive Glow
  // -------------------------------------------------------------------------
  function initStage24FpsCanvas() {
    const canvas = document.getElementById("stage-fx-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const rainDrops = Array.from({ length: 28 }, (_, i) => ({
      x: (i * 45) % 1280,
      y: (i * 67) % 720,
      len: 26 + (i % 14),
      speed: 14 + (i % 7),
    }));

    let lastFrameTime = 0;
    const frameInterval = 1000 / 30; // Capped at 30fps per performance spec

    function isAnyVoiceSpeaking() {
      return (
        (!djPlayer.paused && djPlayer.currentTime > 0) ||
        (!asmrPlayer.paused && asmrPlayer.currentTime > 0) ||
        (!chatVoicePlayer.paused && chatVoicePlayer.currentTime > 0) ||
        Boolean(window.speechSynthesis && window.speechSynthesis.speaking)
      );
    }

    function animateStage(now) {
      requestAnimationFrame(animateStage);
      if (document.hidden) return;
      if (viewFocus && viewFocus.classList.contains("hidden")) return;
      if (now - lastFrameTime < frameInterval) return;
      lastFrameTime = now;

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const t = now * 0.001;

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

      const lampRadius = 150 + 18 * Math.sin(t * 2.1);
      const grad = ctx.createRadialGradient(980, 220, 10, 980, 220, lampRadius);
      grad.addColorStop(0, "rgba(232, 176, 75, 0.16)");
      grad.addColorStop(1, "rgba(232, 176, 75, 0)");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(980, 220, lampRadius, 0, Math.PI * 2);
      ctx.fill();

      const speaking = isAnyVoiceSpeaking();
      if (speaking) {
        const cx = 640;
        const cy = 615;
        ctx.save();
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
  // Sample Card Selection (Mouse-tilt effect disabled per performance spec)
  // -------------------------------------------------------------------------
  function initMouseTracking() {
    function smoothHeroPreview(imgUrl) {
      const previewEl = document.getElementById("hero-preview-img");
      if (!previewEl || !imgUrl) return;
      previewEl.classList.remove("active");
      setTimeout(() => {
        previewEl.src = imgUrl;
        previewEl.onload = () => {
          previewEl.classList.add("active");
        };
      }, 140);
    }

    document.querySelectorAll(".webtoon-day-card").forEach((card) => {
      card.addEventListener("click", async () => {
        document.querySelectorAll(".webtoon-day-card").forEach((c) => c.classList.remove("active-day"));
        card.classList.add("active-day");
        const imgEl = card.querySelector("img");
        if (imgEl && imgEl.src) smoothHeroPreview(imgEl.src);
        const vibe = card.getAttribute("data-vibe");
        if (vibe && customAnswerInput) {
          window.history.pushState({}, "", "/");
          showView("question");
          openSurveyStage();
          if (!currentSession) await startNewSession();
          customAnswerInput.value = vibe;
          customAnswerInput.focus();
        }
      });
    });

    document.querySelectorAll(".k-landmark-card").forEach((card) => {
      card.addEventListener("click", async () => {
        document.querySelectorAll(".k-landmark-card").forEach((c) => c.classList.remove("active-landmark"));
        card.classList.add("active-landmark");
        const imgEl = card.querySelector("img");
        if (imgEl && imgEl.src) smoothHeroPreview(imgEl.src);
        const bgPrompt = card.getAttribute("data-bg-prompt");
        const bgLabel = card.getAttribute("data-bg-label");
        if (bgPrompt && customAnswerInput) {
          window.history.pushState({}, "", "/");
          showView("question");
          openSurveyStage();
          if (!currentSession) await startNewSession();
          customAnswerInput.value = `${bgLabel} — ${bgPrompt}`;
          customAnswerInput.focus();
        }
      });
    });
  }

  // -------------------------------------------------------------------------
  // Autonomous Persona Agent Chat + Live Voice Recognition (STT) + Door Transform
  // -------------------------------------------------------------------------
  let sttRecognition = null;
  let sttListening = false;
  let continuousVoiceMode = false;

  function speakFallbackTTS(text, onDone) {
    if (!window.speechSynthesis || !text) {
      if (onDone) onDone();
      return;
    }
    try {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      const hasKorean = /[가-힣]/.test(text);
      utter.lang = hasKorean ? "ko-KR" : "en-US";
      utter.rate = 0.98;
      utter.pitch = 1.05;
      utter.onend = () => {
        if (onDone) onDone();
      };
      utter.onerror = () => {
        if (onDone) onDone();
      };
      window.speechSynthesis.speak(utter);
    } catch (_) {
      if (onDone) onDone();
    }
  }

  function appendChatBubble(role, sender, text, narration = "", innerThought = "") {
    const box = document.getElementById("chat-messages-box");
    if (!box) return;
    const div = document.createElement("div");
    div.className = `chat-bubble ${role}`;

    const safeNarration = narration
      ? `<div class="chat-narration">*${narration.replace(/^\*|\*$/g, "")}*</div>`
      : "";
    const safeText = role === "assistant" ? `"${text.replace(/^"|"$/g, "")}"` : text;
    const safeThought =
      role === "assistant" && innerThought
        ? `<div class="chat-inner-thought-wrap">
             <button type="button" class="inner-thought-toggle-btn" onclick="this.nextElementSibling.classList.toggle('hidden')">
               💭 속마음 보기
             </button>
             <div class="chat-inner-thought hidden">${innerThought}</div>
           </div>`
        : "";

    div.innerHTML = `
      <div class="chat-sender">${sender}</div>
      ${safeNarration}
      <div class="chat-text">${safeText}</div>
      ${safeThought}
    `;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  function renderSuggestedReplies(replies) {
    const wrap = document.getElementById("suggested-chips-wrap");
    if (!wrap || !Array.isArray(replies) || !replies.length) return;
    wrap.innerHTML = "";
    replies.slice(0, 3).forEach((rep) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "suggested-reply-chip";
      btn.setAttribute("data-reply", rep);
      btn.textContent = `"${rep.replace(/^"|"$/g, "")}"`;
      btn.addEventListener("click", () => {
        sendCompanionChat(rep);
      });
      wrap.appendChild(btn);
    });
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

  async function sendCompanionChat(messageText, episodeContext = null) {
    if (!currentSession || !messageText.trim()) return;
    const msg = messageText.trim();
    const chatInput = document.getElementById("chat-input");
    if (chatInput) chatInput.value = "";

    const nickEl = document.getElementById("user-nickname-input");
    const relEl = document.getElementById("relationship-preset-select");
    const userNickname = (nickEl && nickEl.value.trim()) || googleUser.name || "메이트";
    const relationshipPreset =
      (relEl && relEl.value) || "다정한 선배 · 메이트 (Warm Senior / Study Mate)";

    appendChatBubble("user", `${userNickname} (나)`, msg);

    const res = await fetch(`/api/session/${currentSession.session_id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: msg,
        lang: currentLang,
        user_nickname: userNickname,
        relationship_preset: relationshipPreset,
        episode_context: episodeContext,
      }),
    });
    if (!res.ok) return;
    const reply = await res.json();

    const charName = (currentSession.spec && currentSession.spec.name) || "Sora";
    const spokenText = reply.reply_text || reply.reply || "...";
    const narrationText = reply.narration || "";
    const innerThoughtText = reply.inner_thought || "";

    appendChatBubble(
      "assistant",
      `${charName} // Studio Companion`,
      spokenText,
      narrationText,
      innerThoughtText
    );
    document.getElementById("focus-subtitle-box").textContent = `"${spokenText}"`;

    // Update Voice Call Overlay transcript if open
    const callNarration = document.getElementById("voice-call-narration");
    const callLine = document.getElementById("voice-call-line");
    const callThought = document.getElementById("voice-call-thought");
    if (callNarration && narrationText) {
      callNarration.textContent = `*${narrationText.replace(/^\*|\*$/g, "")}*`;
    }
    if (callLine) callLine.textContent = `"${spokenText}"`;
    if (callThought && innerThoughtText) callThought.textContent = innerThoughtText;

    // Update Affection / Bond Level & Emotion State
    if (typeof reply.affection_score === "number") {
      currentSession.affection_score = reply.affection_score;
      currentSession.bond_level_title = reply.bond_level_title;
      updateAffectionUI(
        reply.affection_score,
        reply.bond_level_title,
        reply.affection_delta || 8
      );
    }
    if (reply.emotion_state) {
      currentSession.current_emotion = reply.emotion_state;
      updateEmotionUI(reply.emotion_state);
    }
    if (reply.suggested_replies && reply.suggested_replies.length) {
      renderSuggestedReplies(reply.suggested_replies);
    }

    const onVoiceFinished = () => {
      bgmPlayer.volume = 0.55;
      if (continuousVoiceMode && !sttListening) {
        startVoiceRecognition();
      }
    };

    if (reply.audio_url) {
      chatVoicePlayer.src = reply.audio_url;
      bgmPlayer.volume = 0.22;
      chatVoicePlayer.onended = onVoiceFinished;
      chatVoicePlayer.play().catch(() => {
        speakFallbackTTS(spokenText, onVoiceFinished);
      });
    } else {
      bgmPlayer.volume = 0.22;
      speakFallbackTTS(spokenText, onVoiceFinished);
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

  function startVoiceRecognition() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    const micBtn = document.getElementById("chat-mic-btn");
    const statusBox = document.getElementById("voice-stt-status");
    const chatInput = document.getElementById("chat-input");

    if (!SpeechRec) {
      if (statusBox) {
        statusBox.classList.remove("hidden");
        statusBox.textContent =
          "이 브라우저는 Web Speech API 음성 인식을 지원하지 않습니다 (Chrome/Edge 권장). 텍스트로 대화해주세요.";
      }
      return;
    }

    if (sttListening && sttRecognition) {
      sttRecognition.stop();
      return;
    }

    sttRecognition = new SpeechRec();
    sttRecognition.lang = currentLang === "ko" ? "ko-KR" : "en-US";
    sttRecognition.interimResults = true;
    sttRecognition.maxAlternatives = 1;

    let finalTranscript = "";

    sttRecognition.onstart = () => {
      sttListening = true;
      if (micBtn) micBtn.classList.add("listening");
      if (statusBox) {
        statusBox.classList.remove("hidden");
        statusBox.textContent =
          currentLang === "ko"
            ? "🎙️ 듣고 있어요... 편하게 말을 걸어보세요!"
            : "🎙️ Listening... Speak to your companion!";
      }
    };

    sttRecognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += transcript;
        } else {
          interim += transcript;
        }
      }
      if (chatInput) {
        chatInput.value = (finalTranscript || interim).trim();
      }
      if (statusBox && (finalTranscript || interim)) {
        statusBox.textContent = `🎙️ "${(finalTranscript || interim).trim()}"`;
      }
    };

    sttRecognition.onerror = () => {
      sttListening = false;
      if (micBtn) micBtn.classList.remove("listening");
      if (statusBox) statusBox.classList.add("hidden");
    };

    sttRecognition.onend = () => {
      sttListening = false;
      if (micBtn) micBtn.classList.remove("listening");
      const textToSend = (finalTranscript || (chatInput && chatInput.value) || "").trim();
      if (textToSend) {
        if (statusBox) {
          statusBox.textContent =
            currentLang === "ko"
              ? `✓ 음성 인식 완료: "${textToSend}" — 답장 생성 중...`
              : `✓ Recognized: "${textToSend}" — replying...`;
          setTimeout(() => statusBox.classList.add("hidden"), 2200);
        }
        sendCompanionChat(textToSend);
      } else if (statusBox && !continuousVoiceMode) {
        statusBox.classList.add("hidden");
      }
    };

    try {
      sttRecognition.start();
    } catch (_) {
      sttListening = false;
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
              STUDIO MINI-ROOM // ${item.minihompy_title || "Late-Night Room"}
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

  // Primary "Try Now!" & Survey Stage triggers — only call /api/session/start when user presses Start
  async function triggerTryNowSurvey() {
    window.history.pushState({}, "", "/");
    showView("question");
    openSurveyStage();
    if (!currentSession || currentSession.status !== "questioning") {
      await startNewSession();
    }
  }

  ["header-try-now-btn", "hero-try-now-btn", "finder-try-survey-link", "nav-discovery-btn", "about-start-btn"].forEach(
    (btnId) => {
      const btn = document.getElementById(btnId);
      if (btn) {
        btn.addEventListener("click", (e) => {
          e.preventDefault();
          triggerTryNowSurvey();
        });
      }
    }
  );

  const backToLandingBtn = document.getElementById("back-to-landing-btn");
  if (backToLandingBtn) {
    backToLandingBtn.addEventListener("click", () => {
      window.history.pushState({}, "", "/");
      showView("question");
      openLandingStage();
    });
  }

  const navHowLink = document.getElementById("nav-how-link");
  if (navHowLink) {
    navHowLink.addEventListener("click", (e) => {
      e.preventDefault();
      window.history.pushState({}, "", "/");
      showView("question");
      openLandingStage();
      const howEl = document.getElementById("how-it-works");
      if (howEl) howEl.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  document.getElementById("nav-studio-btn").addEventListener("click", async (e) => {
    e.preventDefault();
    const sid = (currentSession && currentSession.session_id) || "default";
    window.history.pushState({}, "", `/demo/${sid}`);
    if (!currentSession) {
      const res = await fetch(`/api/session/${sid}`);
      if (res.ok) currentSession = await res.json();
    }
    if (currentSession) renderStudioView(currentSession);
    showView("studio");
  });
  document.getElementById("nav-focus-btn").addEventListener("click", async (e) => {
    e.preventDefault();
    const sid = (currentSession && currentSession.session_id) || "default";
    window.history.pushState({}, "", `/study/${sid}`);
    if (!currentSession) {
      const res = await fetch(`/api/session/${sid}`);
      if (res.ok) currentSession = await res.json();
    }
    if (currentSession) renderFocusView(currentSession);
    showView("focus");
  });
  document.getElementById("nav-market-btn").addEventListener("click", (e) => {
    e.preventDefault();
    window.history.pushState({}, "", "/marketplace");
    showView("marketplace");
  });
  const finderGalleryLink = document.getElementById("finder-gallery-link");
  if (finderGalleryLink) {
    finderGalleryLink.addEventListener("click", (e) => {
      e.preventDefault();
      window.history.pushState({}, "", "/marketplace");
      showView("marketplace");
    });
  }
  document.getElementById("nav-about-btn").addEventListener("click", (e) => {
    e.preventDefault();
    window.history.pushState({}, "", "/about");
    showView("about");
  });

  // Survey Mode Cards
  document.querySelectorAll(".survey-mode-card").forEach((card) => {
    card.addEventListener("click", () => {
      surveyMode = card.getAttribute("data-mode") || "staged";
      maxTurnsMode = parseInt(card.getAttribute("data-turns") || "18", 10);
      updateModeButtonLabel();
      startNewSession();
      openSurveyStage();
    });
  });

  modeToggleBtn.addEventListener("click", () => {
    if (surveyMode === "staged") {
      surveyMode = "general";
      maxTurnsMode = 10;
    } else if (surveyMode === "general") {
      surveyMode = "quick";
      maxTurnsMode = 6;
    } else {
      surveyMode = "staged";
      maxTurnsMode = 18;
    }
    updateModeButtonLabel();
    startNewSession();
    openSurveyStage();
  });

  // Hero showcase controls
  const heroUnmuteBtn = document.getElementById("hero-unmute-btn");
  const heroLiveVideo = document.getElementById("hero-live-video");
  if (heroUnmuteBtn && heroLiveVideo) {
    heroUnmuteBtn.addEventListener("click", () => {
      heroLiveVideo.muted = !heroLiveVideo.muted;
      heroUnmuteBtn.textContent = heroLiveVideo.muted ? "Unmute Radio" : "Mute Radio";
    });
  }

  // Theme Mode Switcher: Dark / Light / System
  const themeButtons = document.querySelectorAll("[data-theme-choice]");
  const systemLightMedia = window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: light)")
    : null;
  let currentThemeChoice = localStorage.getItem("bias_theme_mode") || "dark";

  function applyThemeChoice(mode) {
    currentThemeChoice = mode || "dark";
    localStorage.setItem("bias_theme_mode", currentThemeChoice);
    themeButtons.forEach((btn) => {
      btn.classList.toggle(
        "active",
        btn.getAttribute("data-theme-choice") === currentThemeChoice
      );
    });
    let resolvedTheme = currentThemeChoice;
    if (currentThemeChoice === "system") {
      resolvedTheme = systemLightMedia && systemLightMedia.matches ? "light" : "dark";
    }
    if (resolvedTheme === "light") {
      document.documentElement.setAttribute("data-theme", "light");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }

  themeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const choice = btn.getAttribute("data-theme-choice") || "dark";
      applyThemeChoice(choice);
    });
  });

  if (systemLightMedia && systemLightMedia.addEventListener) {
    systemLightMedia.addEventListener("change", () => {
      if (currentThemeChoice === "system") {
        applyThemeChoice("system");
      }
    });
  }
  applyThemeChoice(currentThemeChoice);

  // 5 Open-Source Korean Animation / Webtoon Fonts Selector (Lazy @font-face injection)
  const OPEN_SOURCE_FONTS = {
    gmarket: {
      className: "font-vibe-gmarket",
      css: "@font-face { font-family: 'GmarketSansMedium'; src: url('https://fastly.jsdelivr.net/gh/projectnoonnu/noonfonts_2001@1.1/GmarketSansMedium.woff') format('woff'); font-weight: normal; font-style: normal; font-display: swap; }",
    },
    ridi: {
      className: "font-vibe-ridi",
      css: "@font-face { font-family: 'RIDIBatang'; src: url('https://fastly.jsdelivr.net/gh/projectnoonnu/noonfonts_twelve@1.0/RIDIBatang.woff') format('woff'); font-weight: normal; font-style: normal; font-display: swap; }",
    },
    gowun: {
      className: "font-vibe-gowun",
      css: "@font-face { font-family: 'GowunDodum-Regular'; src: url('https://fastly.jsdelivr.net/gh/projectnoonnu/noonfonts_2108@1.1/GowunDodum-Regular.woff') format('woff'); font-weight: normal; font-style: normal; font-display: swap; }",
    },
    cafe24: {
      className: "font-vibe-cafe24",
      css: "@font-face { font-family: 'Cafe24SsurroundAir'; src: url('https://fastly.jsdelivr.net/gh/projectnoonnu/noonfonts_2105_2@1.0/Cafe24SsurroundAir.woff') format('woff'); font-weight: normal; font-style: normal; font-display: swap; }",
    },
    maruburi: {
      className: "font-vibe-maruburi",
      css: "@font-face { font-family: 'MaruBuri-Regular'; src: url('https://fastly.jsdelivr.net/gh/projectnoonnu/noonfonts_20-10-21@1.0/MaruBuri-Regular.woff') format('woff'); font-weight: normal; font-style: normal; font-display: swap; }",
    },
  };
  const injectedFontStyles = {};
  const fontChoiceButtons = document.querySelectorAll(".font-choice-item");

  function applyFontChoice(fontKey) {
    const allFontClasses = Object.values(OPEN_SOURCE_FONTS).map((f) => f.className);
    document.body.classList.remove("font-vibe-anime", "font-vibe-lyric", ...allFontClasses);
    fontChoiceButtons.forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-font-choice") === fontKey);
    });
    if (fontKey && OPEN_SOURCE_FONTS[fontKey]) {
      const def = OPEN_SOURCE_FONTS[fontKey];
      if (!injectedFontStyles[fontKey]) {
        const styleEl = document.createElement("style");
        styleEl.setAttribute("data-open-font", fontKey);
        styleEl.textContent = def.css;
        document.head.appendChild(styleEl);
        injectedFontStyles[fontKey] = true;
      }
      document.body.classList.add(def.className);
    }
    localStorage.setItem("bias_font_choice", fontKey || "studio");
  }

  fontChoiceButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const choice = btn.getAttribute("data-font-choice") || "studio";
      applyFontChoice(choice);
    });
  });

  const savedFontChoice = localStorage.getItem("bias_font_choice") || "studio";
  if (savedFontChoice !== "studio") {
    applyFontChoice(savedFontChoice);
  }

  // Study Room 10 Korean Landmarks Instant Studio Door Switcher
  document.querySelectorAll(".studio-bg-chip").forEach((chip) => {
    chip.addEventListener("click", async () => {
      document.querySelectorAll(".studio-bg-chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      const prompt = chip.getAttribute("data-prompt");
      const label = chip.getAttribute("data-label");
      if (prompt) {
        await executeDoorTransformation("change_background", prompt, label);
      }
    });
  });

  // Toss Segmented Result Tabs in #view-focus
  const focusTabBtns = document.querySelectorAll("[data-focus-tab]");
  focusTabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const tabKey = btn.getAttribute("data-focus-tab");
      focusTabBtns.forEach((b) => b.classList.toggle("active", b === btn));
      ["cowork", "style", "vocal", "export"].forEach((k) => {
        const panel = document.getElementById(`focus-tab-${k}`);
        if (!panel) return;
        if (k === tabKey) {
          panel.classList.remove("hidden");
        } else {
          panel.classList.add("hidden");
        }
      });
    });
  });

  // Studio Lighting / Mood Filter Switcher (4 Presets on #focus-stage-frame)
  const stageLightingPills = document.querySelectorAll(".lighting-pill");
  const focusStageFrame = document.getElementById("focus-stage-frame");
  stageLightingPills.forEach((pill) => {
    pill.addEventListener("click", () => {
      stageLightingPills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      const mode = pill.getAttribute("data-lighting") || "amber";
      if (focusStageFrame) {
        focusStageFrame.classList.remove(
          "lighting-amber",
          "lighting-rain-blue",
          "lighting-sunset",
          "lighting-cyber"
        );
        focusStageFrame.classList.add(`lighting-${mode}`);
      }
    });
  });

  // User Persona / Nickname & Relationship Preset Sync (Zeta / Caveduck / Wrtn Style)
  async function syncUserPersonaSettings() {
    if (!currentSession) return;
    const nickEl = document.getElementById("user-nickname-input");
    const relEl = document.getElementById("relationship-preset-select");
    const user_nickname = (nickEl && nickEl.value.trim()) || "선배님";
    const relationship_preset = (relEl && relEl.value) || "다정한 선후배 메이트";
    currentSession.user_nickname = user_nickname;
    currentSession.relationship_preset = relationship_preset;
    try {
      await fetch(`/api/session/${currentSession.session_id}/persona`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_nickname, relationship_preset }),
      });
    } catch (_) {}
  }

  const userNickInput = document.getElementById("user-nickname-input");
  const relPresetSelect = document.getElementById("relationship-preset-select");
  if (userNickInput) {
    userNickInput.addEventListener("change", syncUserPersonaSettings);
  }
  if (relPresetSelect) {
    relPresetSelect.addEventListener("change", syncUserPersonaSettings);
  }

  // Episode Scenario Starter Chips (Zeta / Wrtn / LoveyDovey Style)
  document.querySelectorAll(".episode-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".episode-chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      const episode = chip.getAttribute("data-episode") || "";
      const promptMsg = chip.getAttribute("data-prompt") || episode;
      if (promptMsg) {
        sendCompanionChat(promptMsg, episode);
      }
    });
  });

  // Initial Suggested Reply Chips
  document.querySelectorAll("#suggested-replies-bar .suggested-reply-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const p = chip.getAttribute("data-reply") || chip.textContent;
      if (p) sendCompanionChat(p);
    });
  });

  // Spirit City / gogh Style Co-Working To-Do Checklist
  const todoListContainer = document.getElementById("todo-list-container");
  const todoProgressBadge = document.getElementById("todo-progress-badge");
  const todoNewInput = document.getElementById("todo-new-input");
  const todoAddBtn = document.getElementById("todo-add-btn");

  function updateTodoProgress(celebrateTaskText = null) {
    if (!todoListContainer || !todoProgressBadge) return;
    const boxes = todoListContainer.querySelectorAll(".todo-check");
    const total = boxes.length;
    let done = 0;
    boxes.forEach((b) => {
      if (b.checked) done += 1;
    });
    todoProgressBadge.textContent = `${done} / ${total} 완료`;
    if (celebrateTaskText && currentSession) {
      sendCompanionChat(`방금 목표 하나 완료했어: "${celebrateTaskText}" 칭찬해줘!`);
    }
  }

  if (todoListContainer) {
    todoListContainer.addEventListener("change", (e) => {
      if (e.target && e.target.classList.contains("todo-check")) {
        const span = e.target.parentElement.querySelector(".todo-text");
        const taskLabel = span ? span.textContent : "집중 목표";
        updateTodoProgress(e.target.checked ? taskLabel : null);
      }
    });
  }

  function addNewTodoItem() {
    if (!todoNewInput || !todoListContainer) return;
    const txt = todoNewInput.value.trim();
    if (!txt) return;
    const label = document.createElement("label");
    label.className = "todo-item";
    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.className = "todo-check";
    const span = document.createElement("span");
    span.className = "todo-text";
    span.textContent = txt;
    label.appendChild(chk);
    label.appendChild(span);
    todoListContainer.appendChild(label);
    todoNewInput.value = "";
    updateTodoProgress(null);
  }

  if (todoAddBtn) {
    todoAddBtn.addEventListener("click", addNewTodoItem);
  }
  if (todoNewInput) {
    todoNewInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") addNewTodoItem();
    });
  }

  // 3-Channel Web Audio Procedural Ambient ASMR Soundscape Mixer (Rain / Fountain Pen & Keys / Fireplace Vinyl)
  let asmrAudioCtx = null;
  let asmrChannels = {};

  function ensureAsmrAudioEngine() {
    if (asmrAudioCtx) {
      if (asmrAudioCtx.state === "suspended") asmrAudioCtx.resume();
      return;
    }
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;
    asmrAudioCtx = new AudioContextClass();

    const bufferSize = asmrAudioCtx.sampleRate * 3;
    // 1. Rain pink noise buffer
    const rainBuf = asmrAudioCtx.createBuffer(1, bufferSize, asmrAudioCtx.sampleRate);
    const rainData = rainBuf.getChannelData(0);
    let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
    for (let i = 0; i < bufferSize; i++) {
      const white = Math.random() * 2 - 1;
      b0 = 0.99886 * b0 + white * 0.0555179;
      b1 = 0.99332 * b1 + white * 0.0750759;
      b2 = 0.96900 * b2 + white * 0.1538520;
      b3 = 0.86650 * b3 + white * 0.3104856;
      b4 = 0.55000 * b4 + white * 0.5329522;
      b5 = -0.7616 * b5 - white * 0.0168980;
      rainData[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362) * 0.035;
      b6 = white * 0.115926;
    }
    const rainSource = asmrAudioCtx.createBufferSource();
    rainSource.buffer = rainBuf;
    rainSource.loop = true;
    const rainFilter = asmrAudioCtx.createBiquadFilter();
    rainFilter.type = "bandpass";
    rainFilter.frequency.value = 1100;
    rainFilter.Q.value = 0.7;
    const rainGain = asmrAudioCtx.createGain();
    rainGain.gain.value = 0;
    rainSource.connect(rainFilter);
    rainFilter.connect(rainGain);
    rainGain.connect(asmrAudioCtx.destination);
    rainSource.start();

    // 2. Fountain pen / soft mechanical keystroke impulses buffer
    const keyBuf = asmrAudioCtx.createBuffer(1, bufferSize, asmrAudioCtx.sampleRate);
    const keyData = keyBuf.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) {
      if (Math.random() < 0.00055) {
        const amp = 0.25 + Math.random() * 0.35;
        for (let k = 0; k < 260 && i + k < bufferSize; k++) {
          keyData[i + k] += (Math.random() * 2 - 1) * amp * Math.exp(-k / 48);
        }
      }
    }
    const keySource = asmrAudioCtx.createBufferSource();
    keySource.buffer = keyBuf;
    keySource.loop = true;
    const keyFilter = asmrAudioCtx.createBiquadFilter();
    keyFilter.type = "highpass";
    keyFilter.frequency.value = 850;
    const keyGain = asmrAudioCtx.createGain();
    keyGain.gain.value = 0;
    keySource.connect(keyFilter);
    keyFilter.connect(keyGain);
    keyGain.connect(asmrAudioCtx.destination);
    keySource.start();

    // 3. Fireplace & Vinyl warm crackle + sub warmth buffer
    const fireBuf = asmrAudioCtx.createBuffer(1, bufferSize, asmrAudioCtx.sampleRate);
    const fireData = fireBuf.getChannelData(0);
    let brown = 0;
    for (let i = 0; i < bufferSize; i++) {
      const white = Math.random() * 2 - 1;
      brown = (brown + 0.02 * white) / 1.02;
      let crackle = 0;
      if (Math.random() < 0.0014) {
        crackle = (Math.random() * 2 - 1) * 0.42;
      }
      fireData[i] = brown * 0.22 + crackle;
    }
    const fireSource = asmrAudioCtx.createBufferSource();
    fireSource.buffer = fireBuf;
    fireSource.loop = true;
    const fireGain = asmrAudioCtx.createGain();
    fireGain.gain.value = 0;
    fireSource.connect(fireGain);
    fireGain.connect(asmrAudioCtx.destination);
    fireSource.start();

    asmrChannels = {
      rain: rainGain,
      key: keyGain,
      fire: fireGain,
    };
  }

  [
    { sliderId: "asmr-rain-slider", valId: "asmr-rain-val", key: "rain", scale: 0.45 },
    { sliderId: "asmr-key-slider", valId: "asmr-key-val", key: "key", scale: 0.55 },
    { sliderId: "asmr-fire-slider", valId: "asmr-fire-val", key: "fire", scale: 0.45 },
  ].forEach(({ sliderId, valId, key, scale }) => {
    const slider = document.getElementById(sliderId);
    const valEl = document.getElementById(valId);
    if (!slider) return;
    slider.addEventListener("input", () => {
      ensureAsmrAudioEngine();
      const v = parseInt(slider.value, 10) || 0;
      if (valEl) valEl.textContent = `${v}%`;
      if (asmrChannels[key] && asmrAudioCtx) {
        asmrChannels[key].gain.setTargetAtTime((v / 100) * scale, asmrAudioCtx.currentTime, 0.08);
      }
    });
  });

  // Character.AI / LoveyDovey Style 1:1 Live Voice Call Overlay Modal
  const voiceCallModal = document.getElementById("voice-call-modal");
  const openVoiceCallBtn = document.getElementById("open-voice-call-btn");
  const voiceCallSpeakBtn = document.getElementById("voice-call-speak-btn");
  const voiceCallEndBtn = document.getElementById("voice-call-end-btn");
  const voiceCallTimerEl = document.getElementById("voice-call-timer");
  let voiceCallInterval = null;
  let voiceCallSeconds = 0;

  function openVoiceCallOverlay() {
    if (!voiceCallModal) return;
    voiceCallModal.classList.remove("hidden");
    voiceCallSeconds = 0;
    if (voiceCallTimerEl) voiceCallTimerEl.textContent = "LIVE VOICE CALL · 00:00";
    clearInterval(voiceCallInterval);
    voiceCallInterval = setInterval(() => {
      voiceCallSeconds += 1;
      const m = String(Math.floor(voiceCallSeconds / 60)).padStart(2, "0");
      const s = String(voiceCallSeconds % 60).padStart(2, "0");
      if (voiceCallTimerEl) voiceCallTimerEl.textContent = `LIVE VOICE CALL · ${m}:${s}`;
    }, 1000);
    // Play greeting or trigger voice
    if (currentSession && currentSession.spec) {
      const subEl = document.getElementById("voice-call-subtitle");
      const narEl = document.getElementById("voice-call-narration");
      if (narEl) narEl.textContent = `*${currentSession.spec.first_greeting_narration || "수화기 너머로 잔잔한 빗소리와 숨소리가 들려온다."}*`;
      if (subEl) subEl.textContent = `"${currentSession.spec.first_greeting_line || currentSession.spec.dj_intro_script}"`;
    }
  }

  function closeVoiceCallOverlay() {
    if (!voiceCallModal) return;
    voiceCallModal.classList.add("hidden");
    clearInterval(voiceCallInterval);
    if (continuousVoiceMode && sttListening && sttRecognition) {
      continuousVoiceMode = false;
      sttRecognition.stop();
    }
  }

  if (openVoiceCallBtn) {
    openVoiceCallBtn.addEventListener("click", openVoiceCallOverlay);
  }
  if (voiceCallEndBtn) {
    voiceCallEndBtn.addEventListener("click", closeVoiceCallOverlay);
  }
  if (voiceCallSpeakBtn) {
    voiceCallSpeakBtn.addEventListener("click", () => {
      startVoiceRecognition();
    });
  }

  // Companion Night Study Diary & Letter Modal (LoveyDovey / Caveduck Style)
  const diaryModal = document.getElementById("diary-modal");
  const openDiaryModalBtn = document.getElementById("open-diary-modal-btn");
  const generateDiaryExportBtn = document.getElementById("generate-diary-export-btn");
  const diaryModalClose = document.getElementById("diary-modal-close");
  const diaryRegenerateBtn = document.getElementById("diary-regenerate-btn");
  const diaryDownloadTxtBtn = document.getElementById("diary-download-txt-btn");

  function collectCompletedTodos() {
    if (!todoListContainer) return [];
    const list = [];
    todoListContainer.querySelectorAll(".todo-item").forEach((item) => {
      const chk = item.querySelector(".todo-check");
      const txt = item.querySelector(".todo-text");
      if (chk && chk.checked && txt) {
        list.push(txt.textContent.trim());
      }
    });
    return list;
  }

  async function openAndGenerateDiary() {
    if (!currentSession || !diaryModal) return;
    diaryModal.classList.remove("hidden");
    const titleEl = document.getElementById("diary-letter-title");
    const bodyEl = document.getElementById("diary-letter-body");
    const psEl = document.getElementById("diary-letter-ps");
    const tagEl = document.getElementById("diary-mood-tag");
    const dateEl = document.getElementById("diary-date-badge");

    if (titleEl) titleEl.textContent = `${currentSession.spec ? currentSession.spec.name : "최애"}가 오늘 밤 일기를 적고 있어요...`;
    if (bodyEl) bodyEl.textContent = "만년필 잉크로 오늘 나눈 대화와 집중 시간을 기록하는 중입니다...";
    if (psEl) psEl.textContent = "";

    try {
      const res = await fetch(`/api/session/${currentSession.session_id}/diary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          completed_todos: collectCompletedTodos(),
          focus_minutes: 25,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (dateEl && data.date_label) dateEl.textContent = data.date_label;
        if (tagEl && data.mood_tag) tagEl.textContent = data.mood_tag;
        if (titleEl && data.diary_title) titleEl.textContent = data.diary_title;
        if (bodyEl && data.letter_body) bodyEl.textContent = data.letter_body;
        if (psEl && data.secret_postscript) psEl.textContent = data.secret_postscript;
      }
    } catch (_) {
      if (titleEl) titleEl.textContent = "오늘 밤 우리만의 작업실 기록";
      if (bodyEl) bodyEl.textContent = "오늘도 늦은 시간까지 제 옆에서 함께 집중해 주셔서 정말 고마워요.";
    }
  }

  if (openDiaryModalBtn) {
    openDiaryModalBtn.addEventListener("click", openAndGenerateDiary);
  }
  if (generateDiaryExportBtn) {
    generateDiaryExportBtn.addEventListener("click", openAndGenerateDiary);
  }
  if (diaryModalClose) {
    diaryModalClose.addEventListener("click", () => {
      if (diaryModal) diaryModal.classList.add("hidden");
    });
  }
  if (diaryRegenerateBtn) {
    diaryRegenerateBtn.addEventListener("click", openAndGenerateDiary);
  }
  if (diaryDownloadTxtBtn) {
    diaryDownloadTxtBtn.addEventListener("click", () => {
      const title = (document.getElementById("diary-letter-title") || {}).textContent || "새벽 교환일기";
      const body = (document.getElementById("diary-letter-body") || {}).textContent || "";
      const ps = (document.getElementById("diary-letter-ps") || {}).textContent || "";
      const dateStr = (document.getElementById("diary-date-badge") || {}).textContent || "";
      const fullTxt = `[${dateStr}] ${title}\n\n${body}\n\n${ps}\n`;
      const blob = new Blob([fullTxt], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bias_night_diary_${currentSession ? currentSession.session_id : "note"}.txt`;
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  // Google Connect Modal & 1-Click Account Selector
  const googleModal = document.getElementById("google-modal");
  function openGoogleModal() {
    document.getElementById("google-name-input").value = googleUser.name;
    document.getElementById("google-email-input").value = googleUser.email;
    if (googleModal) googleModal.classList.remove("hidden");
  }
  ["google-connect-btn", "navbar-google-btn", "focus-google-pill-btn"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("click", openGoogleModal);
  });
  document.getElementById("google-modal-close").addEventListener("click", () => {
    googleModal.classList.add("hidden");
  });
  document.getElementById("google-demo-fill-btn").addEventListener("click", () => {
    document.getElementById("google-name-input").value = "Raymond Cho (PM)";
    document.getElementById("google-email-input").value = "raymond.cho@deepmind-hackathon.kr";
  });
  document.querySelectorAll(".google-account-option").forEach((optBtn) => {
    optBtn.addEventListener("click", async () => {
      const gName = optBtn.getAttribute("data-gname") || "Raymond Cho";
      const gEmail = optBtn.getAttribute("data-gemail") || "raymond.cho@deepmind-hackathon.kr";
      document.getElementById("google-name-input").value = gName;
      document.getElementById("google-email-input").value = gEmail;
      await syncGoogleAccountWithServer(gName, gEmail);
      googleModal.classList.add("hidden");
    });
  });
  document.getElementById("google-save-btn").addEventListener("click", async () => {
    const nameVal = document.getElementById("google-name-input").value.trim() || "Raymond Cho";
    const emailVal =
      document.getElementById("google-email-input").value.trim() || "raymond.cho@google-hackathon.kr";
    await syncGoogleAccountWithServer(nameVal, emailVal);
    googleModal.classList.add("hidden");
  });

  newSessionBtn.addEventListener("click", () => {
    startNewSession();
    openSurveyStage();
  });
  brandHomeBtn.addEventListener("click", () => {
    window.history.pushState({}, "", "/");
    showView("question");
    openLandingStage();
  });

  traceToggleBtn.addEventListener("click", () => {
    traceDrawer.classList.toggle("hidden");
    workspaceRoot.classList.toggle("trace-Collapsed");
  });

  visualCardA.addEventListener("click", () => {
    visualCardA.classList.add("selected-pulse");
    const label = visualLabelA.textContent || "Option A";
    sendAnswer(`Option A: ${label}`);
  });
  visualCardB.addEventListener("click", () => {
    visualCardB.classList.add("selected-pulse");
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
      currentLang === "ko" ? "25분 집중 시작" : "Start 25m Focus";
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

  // Persona Agent Chat & Voice Recognition Listeners
  document.getElementById("chat-send-btn").addEventListener("click", () => {
    const inp = document.getElementById("chat-input");
    if (inp && inp.value.trim()) sendCompanionChat(inp.value);
  });
  document.getElementById("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.value.trim()) {
      sendCompanionChat(e.target.value);
    }
  });
  const chatMicBtn = document.getElementById("chat-mic-btn");
  if (chatMicBtn) {
    chatMicBtn.addEventListener("click", () => {
      startVoiceRecognition();
    });
  }
  const voiceAutoToggle = document.getElementById("voice-auto-toggle");
  if (voiceAutoToggle) {
    voiceAutoToggle.addEventListener("click", () => {
      continuousVoiceMode = !continuousVoiceMode;
      voiceAutoToggle.classList.toggle("active", continuousVoiceMode);
      voiceAutoToggle.textContent = continuousVoiceMode
        ? "🎙️ 연속 음성 대화: ON (말걸기 대기 중)"
        : "🎙️ 음성 인식 대화 모드";
      if (continuousVoiceMode && !sttListening) {
        startVoiceRecognition();
      } else if (!continuousVoiceMode && sttListening && sttRecognition) {
        sttRecognition.stop();
      }
    });
  }
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

  // Initial Route Dispatch — Do NOT call /api/session/start on landing page load
  async function init() {
    applyLanguage(currentLang);
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
    // On root "/", show the calm Finder landing stage without calling /api/session/start
    showView("question");
    openLandingStage();
  }

  init();
})();

