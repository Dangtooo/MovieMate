"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const esc = escapeHTML;
const placeholder = "/static/assets/poster-placeholder.svg";
const imageURL = (path, size = "w500") =>
  /^\/[\w.-]+\.(jpg|png|webp)$/i.test(path || "")
    ? `https://image.tmdb.org/t/p/${size}${path}`
    : placeholder;
const movieYear = (movie) => movie.release_date?.slice(0, 4) || "Chưa rõ năm";
const state = {
  user: null,
  genres: [],
  health: null,
  view: "explore",
  genre: "",
  status: "all",
  page: 1,
  query: "",
  year: "",
  sort: "popular",
  movies: [],
  detail: null,
  detailVersion: 0,
  loadVersion: 0,
  authMode: "login",
  chatHistory: [],
  providers: [],
  provider: "auto",
  providerTouched: false,
  chatVersion: 0,
  chatPending: false,
};
let toastTimer;

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && state.user) updateUser(null);
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Không thể xử lý yêu cầu. Vui lòng thử lại.",
    );
  }
  return data;
}

function toast(message, error = false) {
  clearTimeout(toastTimer);
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("error", error);
  node.hidden = false;
  toastTimer = setTimeout(() => {
    node.hidden = true;
  }, 4000);
}

function updateUser(user) {
  state.user = user;
  $("#account-label").textContent = user ? user.name : "Đăng nhập";
  $("#account-button").title = user ? "Tài khoản của bạn" : "Đăng nhập";
}

function applyImageFallbacks(root = document) {
  $$("img", root).forEach((img) => {
    img.addEventListener(
      "error",
      () => {
        if (!img.src.endsWith(placeholder)) img.src = placeholder;
      },
      { once: true },
    );
  });
}

function renderGenres() {
  const row = $("#genre-row");
  if (state.view === "watchlist") {
    row.innerHTML = [
      ["all", "Tất cả"],
      ["want_to_watch", "Muốn xem"],
      ["watched", "Đã xem"],
    ]
      .map(
        ([id, name]) =>
          `<button class="genre-chip ${state.status === id ? "active" : ""}" data-status="${id}" aria-pressed="${state.status === id}">${name}</button>`,
      )
      .join("");
  } else {
    const preferred = [28, 12, 16, 35, 18, 27, 10749, 878, 9648, 80];
    const items = preferred
      .map((id) => state.genres.find((g) => g.id === id))
      .filter(Boolean);
    row.innerHTML =
      `<button class="genre-chip ${!state.genre ? "active" : ""}" data-genre="" aria-pressed="${!state.genre}">Tất cả phim</button>` +
      items
        .map(
          (g) =>
            `<button class="genre-chip ${Number(state.genre) === g.id ? "active" : ""}" data-genre="${g.id}" aria-pressed="${Number(state.genre) === g.id}" ${state.query ? 'disabled title="Xóa tìm kiếm để lọc theo thể loại"' : ""}>${esc(g.name)}</button>`,
        )
        .join("");
  }
}

function renderSkeleton() {
  $("#movie-grid").innerHTML = Array.from(
    { length: 10 },
    () =>
      '<div class="skeleton"><div class="poster-wrap"></div><div class="skeleton-line"></div><div class="skeleton-line short"></div></div>',
  ).join("");
  $("#movie-grid").setAttribute("aria-busy", "true");
  $("#empty-state").hidden = true;
  $("#pagination").hidden = true;
}

function movieCard(movie) {
  const saved = Boolean(movie.watchlist_status);
  return `<article class="movie-card" data-movie-id="${movie.tmdb_id}">
    <div class="poster-wrap">
      <button class="poster-button" data-open-movie="${movie.tmdb_id}" aria-label="Xem chi tiết ${esc(movie.title)}"><img class="poster" src="${imageURL(movie.poster_path)}" alt="Poster ${esc(movie.title)}" loading="lazy" width="300" height="450"></button>
      <span class="rating-pill" title="Điểm TMDB"><span aria-hidden="true">★</span> ${Number(movie.tmdb_rating).toFixed(1)}</span>
      <button class="save-movie ${saved ? "saved" : ""}" data-save-movie="${movie.tmdb_id}" aria-label="${saved ? "Bỏ lưu" : "Lưu"} ${esc(movie.title)}" aria-pressed="${saved}">${saved ? "✓" : "+"}</button>
      ${movie.watchlist_status === "watched" ? '<span class="watched-badge">Đã xem</span>' : ""}
    </div>
    <button class="movie-title" data-open-movie="${movie.tmdb_id}" title="${esc(movie.title)}">${esc(movie.title)}</button>
    <div class="movie-meta"><span>${movieYear(movie)}</span><span>·</span><span class="genre-label">${esc(movie.genres[0] || "Điện ảnh")}</span>${movie.runtime ? `<span>· ${movie.runtime}′</span>` : ""}</div>
    <div class="review-count">${movie.review_count ? `${movie.review_count} review · ${movie.community_rating}/10 từ cộng đồng` : "Chờ góc nhìn đầu tiên"}</div>
  </article>`;
}

async function loadMovies({ scroll = false } = {}) {
  const version = ++state.loadVersion;
  renderSkeleton();
  renderGenres();
  $("#catalog-notice").hidden = true;
  const isWatchlist = state.view === "watchlist";
  $("#hero").hidden = isWatchlist;
  $("#bot-banner").hidden = isWatchlist;
  $(".toolbar").hidden = isWatchlist;
  $("#catalog-title").textContent = isWatchlist
    ? "Tủ phim của bạn."
    : "Hôm nay, xem gì?";
  $("#catalog-kicker").textContent = isWatchlist
    ? "LƯU LẠI NHỮNG CÂU CHUYỆN"
    : "CHỌN MỘT CÂU CHUYỆN";
  $("#explore-nav").classList.toggle("active", !isWatchlist);
  $("#watchlist-nav").classList.toggle("active", isWatchlist);
  $("#reset-filters").hidden =
    isWatchlist ||
    !(state.genre || state.query || state.year || state.sort !== "popular");
  $("#sort-filter").disabled = Boolean(state.query);
  const params = new URLSearchParams({ page: state.page });
  if (isWatchlist) {
    params.set("status", state.status);
  } else {
    if (state.query) params.set("q", state.query);
    if (state.genre) params.set("genre", state.genre);
    if (state.year) params.set("year", state.year);
    params.set("sort", state.sort);
  }
  if (scroll) $("#catalog").scrollIntoView({ behavior: "smooth" });
  try {
    const data = await api(
      `${isWatchlist ? "/watchlist" : "/movies"}?${params}`,
    );
    if (version !== state.loadVersion) return;
    state.movies = data.items;
    $("#movie-grid").innerHTML = data.items.map(movieCard).join("");
    $("#empty-state").hidden = data.items.length > 0;
    $("#empty-state h3").textContent = isWatchlist
      ? "Tủ phim đang chờ những câu chuyện"
      : "Chưa tìm thấy câu chuyện phù hợp";
    $("#empty-state p").textContent = isWatchlist
      ? "Nhấn dấu + trên một poster để lưu phim muốn xem."
      : "Thử một tên phim khác hoặc bỏ bớt bộ lọc nhé.";
    $("#results-count").textContent =
      `${Number(data.total).toLocaleString("vi-VN")} bộ phim${state.query ? ` cho “${state.query}”` : ""}`;
    $("#catalog-status").textContent = isWatchlist
      ? "Bộ sưu tập cá nhân"
      : data.source === "tmdb"
        ? "Khám phá cùng TMDB"
        : data.source === "cached"
          ? "Danh mục đã lưu"
          : "Danh mục mẫu · 24 phim";
    const notice =
      data.warning ||
      (!isWatchlist && data.source === "local"
        ? "Bạn đang xem danh mục mẫu, thông tin và điểm số chỉ để chạy thử. Thêm TMDB_ACCESS_TOKEN trong .env để tìm kiếm kho phim TMDB và cập nhật thông tin thực tế."
        : "");
    $("#catalog-notice").textContent = notice;
    $("#catalog-notice").hidden = !notice;
    $("#pagination").hidden = data.total_pages <= 1;
    $("#page-label").textContent = `${data.page} / ${data.total_pages}`;
    $("#prev-page").disabled = data.page <= 1;
    $("#next-page").disabled = data.page >= data.total_pages;
    applyImageFallbacks($("#movie-grid"));
  } catch (error) {
    if (version !== state.loadVersion) return;
    $("#results-count").textContent = "Chưa tải được danh sách phim";
    $("#movie-grid").innerHTML =
      `<div class="error-panel"><h3>Kết nối đang gián đoạn</h3><p>${esc(error.message)}</p><button class="button secondary" id="retry-catalog">Thử lại ↺</button></div>`;
    $("#retry-catalog").addEventListener("click", () => loadMovies());
  } finally {
    if (version === state.loadVersion)
      $("#movie-grid").setAttribute("aria-busy", "false");
  }
}

function resetFilters() {
  state.view = "explore";
  state.genre = "";
  state.query = "";
  state.year = "";
  state.sort = "popular";
  state.page = 1;
  $("#search-input").value = "";
  $("#year-filter").value = "";
  $("#sort-filter").value = "popular";
  loadMovies();
}

function openAuth(mode = "login") {
  state.authMode = mode;
  const signedIn = Boolean(state.user);
  $("#auth-title").textContent = signedIn
    ? `Chào ${state.user.name}.`
    : "Thêm một góc nhìn.";
  $("#auth-subtitle").textContent = signedIn
    ? "Những câu chuyện của bạn luôn ở đây."
    : "Đăng nhập để lưu phim và chia sẻ cảm nhận.";
  $("#auth-form").hidden = signedIn;
  $(".auth-tabs").hidden = signedIn;
  $("#account-info").hidden = !signedIn;
  if (signedIn) $("#account-email").textContent = state.user.email;
  $("#name-field").hidden = mode !== "register";
  $("#auth-name").required = mode === "register";
  $("#auth-password").autocomplete =
    mode === "register" ? "new-password" : "current-password";
  $("#login-tab").classList.toggle("active", mode === "login");
  $("#register-tab").classList.toggle("active", mode === "register");
  $("#auth-submit").textContent =
    mode === "register" ? "Tạo tài khoản ↗" : "Đăng nhập ↗";
  $("#auth-error").textContent = "";
  if (!$("#auth-dialog").open) $("#auth-dialog").showModal();
}

async function submitAuth(event) {
  event.preventDefault();
  const submit = $("#auth-submit");
  submit.disabled = true;
  $("#auth-error").textContent = "";
  const payload = {
    email: $("#auth-email").value.trim(),
    password: $("#auth-password").value,
  };
  if (state.authMode === "register")
    payload.name = $("#auth-name").value.trim();
  try {
    const user = await api(`/auth/${state.authMode}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    updateUser(user);
    $("#auth-dialog").close();
    $("#auth-form").reset();
    toast(`Chào ${user.name}, chúc bạn một buổi xem phim thật hay!`);
    loadMovies();
    if ($("#movie-dialog").open && state.detail)
      openMovie(state.detail.tmdb_id);
  } catch (error) {
    $("#auth-error").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

async function toggleSave(id, button) {
  if (!state.user) {
    openAuth();
    return;
  }
  const movie =
    state.movies.find((m) => m.tmdb_id === id) ||
    (state.detail?.tmdb_id === id ? state.detail : null);
  const saved = movie?.watchlist_status;
  if (button) button.disabled = true;
  try {
    await api(`/watchlist/${id}`, {
      method: saved ? "DELETE" : "PUT",
      ...(saved ? {} : { body: JSON.stringify({ status: "want_to_watch" }) }),
    });
    toast(
      saved ? "Đã bỏ phim khỏi tủ phim." : "Đã thêm vào danh sách muốn xem.",
    );
    if (movie) movie.watchlist_status = saved ? null : "want_to_watch";
    if (state.detail?.tmdb_id === id)
      state.detail.watchlist_status = saved ? null : "want_to_watch";
    loadMovies();
    if ($("#movie-dialog").open && state.detail?.tmdb_id === id) openMovie(id);
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

async function markWatched(id, button) {
  if (!state.user) {
    openAuth();
    return;
  }
  button.disabled = true;
  try {
    const status =
      state.detail?.watchlist_status === "watched"
        ? "want_to_watch"
        : "watched";
    await api(`/watchlist/${id}`, {
      method: "PUT",
      body: JSON.stringify({ status }),
    });
    toast(
      status === "watched"
        ? "Đã xem! Ciné bot sẽ tránh gợi ý lại phim này."
        : "Đã chuyển sang danh sách muốn xem.",
    );
    loadMovies();
    openMovie(id);
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

async function openMovie(id) {
  const dialog = $("#movie-dialog");
  const version = ++state.detailVersion;
  if (!dialog.open) dialog.showModal();
  $("#movie-detail").innerHTML =
    '<div class="detail-loading">Đang mở một thế giới mới…</div>';
  try {
    const [movie, reviews, ownReview] = await Promise.all([
      api(`/movies/${id}`),
      api(`/movies/${id}/reviews`),
      state.user ? api(`/movies/${id}/reviews/me`) : Promise.resolve(null),
    ]);
    if (version !== state.detailVersion || !dialog.open) return;
    state.detail = movie;
    const trailer = /^[\w-]{6,30}$/.test(movie.trailer_key || "")
      ? `<a class="button secondary" href="https://www.youtube.com/watch?v=${encodeURIComponent(movie.trailer_key)}" target="_blank" rel="noopener noreferrer">▷ Xem trailer</a>`
      : "";
    $("#movie-detail").innerHTML =
      `<div class="detail-cover">${movie.backdrop_path ? `<img src="${imageURL(movie.backdrop_path, "w1280")}" alt="Bối cảnh ${esc(movie.title)}">` : ""}</div>
      <div class="detail-body"><div class="detail-top"><img class="detail-poster" src="${imageURL(movie.poster_path)}" alt="Poster ${esc(movie.title)}" width="145" height="218"><div class="detail-info"><div class="eyebrow">MỖI BỘ PHIM, MỘT GÓC NHÌN</div><h2 id="detail-title">${esc(movie.title)}</h2><div class="detail-meta"><span>${movieYear(movie)}</span>${movie.runtime ? `<span>· ${movie.runtime} phút</span>` : ""}<span>· ${esc(movie.original_language.toUpperCase())}</span></div><div class="detail-genres">${movie.genres.map((g) => `<span>${esc(g)}</span>`).join("")}</div></div></div>
      <div class="detail-actions"><button class="button primary" id="detail-save">${movie.watchlist_status ? "✓ Đã lưu · Bỏ lưu" : "+ Thêm vào tủ phim"}</button><button class="button secondary" id="detail-watched">${movie.watchlist_status === "watched" ? "✓ Đã xem · Đánh dấu chưa xem" : "◎ Đánh dấu đã xem"}</button>${trailer}</div>
      ${movie.warning ? `<div class="notice">${esc(movie.warning)}</div>` : ""}
      <p class="detail-overview">${esc(movie.overview || "Chưa có tóm tắt cho bộ phim này.")}</p>${movie.cast_names?.length ? `<p class="detail-cast"><strong>Diễn viên</strong> &nbsp; ${movie.cast_names.map(esc).join(" · ")}</p>` : ""}
      <div class="rating-summary"><div><strong><span class="star">★</span> ${Number(movie.tmdb_rating).toFixed(1)}<span> / 10</span></strong><small>${state.health?.tmdb_configured ? "Điểm TMDB" : "Điểm TMDB · dữ liệu mẫu"}</small></div><div><strong>${movie.community_rating ?? "—"}<span> / 10</span></strong><small>Cộng đồng Cinéphile · ${movie.review_count} review</small></div></div>
      <div class="reviews-heading"><h3>Góc nhìn của bạn.</h3><span>${reviews.total} review</span></div>
      ${state.user ? reviewFormHTML(ownReview) : '<p class="review-login"><button id="review-login-button">Đăng nhập</button> để viết review đầu tiên của bạn về bộ phim này.</p>'}
      <div id="reviews-list">${reviews.items.length ? reviews.items.map(reviewHTML).join("") : '<p class="review-empty">Chưa có review. Hãy là người chia sẻ cảm nhận đầu tiên.</p>'}</div>
      <button class="text-button" id="more-reviews" ${reviews.total_pages <= 1 ? "hidden" : ""}>Đọc thêm review ↓</button></div>`;
    dialog.setAttribute("aria-labelledby", "detail-title");
    $("#detail-save").addEventListener("click", (e) =>
      toggleSave(id, e.currentTarget),
    );
    $("#detail-watched").addEventListener("click", (e) =>
      markWatched(id, e.currentTarget),
    );
    $("#review-login-button")?.addEventListener("click", () => openAuth());
    $("#review-form")?.addEventListener("submit", (event) =>
      submitReview(event, id),
    );
    $("#delete-own-review")?.addEventListener("click", () => deleteReview(id));
    let reviewPage = 1;
    $("#more-reviews").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        const nextPage = reviewPage + 1;
        const data = await api(`/movies/${id}/reviews?page=${nextPage}`);
        if (version !== state.detailVersion) return;
        reviewPage = nextPage;
        $("#reviews-list").insertAdjacentHTML(
          "beforeend",
          data.items.map(reviewHTML).join(""),
        );
        button.hidden = reviewPage >= data.total_pages;
      } catch (error) {
        toast(error.message, true);
      } finally {
        button.disabled = false;
      }
    });
    applyImageFallbacks($("#movie-detail"));
  } catch (error) {
    if (version !== state.detailVersion || !dialog.open) return;
    $("#movie-detail").innerHTML =
      `<div class="error-panel"><h3>Chưa mở được bộ phim</h3><p>${esc(error.message)}</p><button class="button secondary" id="retry-detail">Thử lại</button></div>`;
    dialog.removeAttribute("aria-labelledby");
    $("#retry-detail").addEventListener("click", () => openMovie(id));
  }
}

function reviewFormHTML(review) {
  return `<form class="review-form" id="review-form"><h4>${review ? "Cập nhật góc nhìn của bạn" : "Bạn nghĩ gì về bộ phim này?"}</h4><label class="review-score">Điểm của bạn<select id="review-rating" required>${Array.from({ length: 10 }, (_, i) => `<option value="${i + 1}" ${(review?.rating ?? 8) === i + 1 ? "selected" : ""}>${i + 1} / 10</option>`).join("")}</select></label><label>Cảm nhận<textarea id="review-content" minlength="10" maxlength="3000" required placeholder="Điều gì khiến bạn nhớ đến bộ phim này? (ít nhất 10 ký tự)">${esc(review?.content || "")}</textarea></label><div class="review-form-bottom"><label class="checkbox-label"><input id="review-spoiler" type="checkbox" ${review?.contains_spoiler ? "checked" : ""}>Review có tiết lộ nội dung</label><button class="button primary" id="review-submit" type="submit">${review ? "Cập nhật review" : "Đăng review"} ↗</button></div><p class="form-error" id="review-error" role="alert"></p>${review ? '<div class="review-tools"><button class="text-button danger-button" id="delete-own-review" type="button">Xóa review của tôi</button></div>' : ""}</form>`;
}

function reviewHTML(review) {
  const date = new Date(review.created_at).toLocaleDateString("vi-VN");
  return `<article class="review-item"><div class="review-head"><span class="review-avatar" aria-hidden="true">${esc(review.author.slice(0, 1).toUpperCase())}</span><div class="review-author">${esc(review.author)}${review.user_id === state.user?.id ? '<span class="review-own">Bạn</span>' : ""}<small>${date}</small></div><span class="review-score-badge">★ ${review.rating}/10</span></div>${review.contains_spoiler ? `<details><summary class="spoiler-summary">Có tiết lộ nội dung · Nhấn để đọc</summary><p class="review-text">${esc(review.content)}</p></details>` : `<p class="review-text">${esc(review.content)}</p>`}</article>`;
}

async function submitReview(event, id) {
  event.preventDefault();
  $("#review-submit").disabled = true;
  $("#review-error").textContent = "";
  try {
    await api(`/movies/${id}/reviews/me`, {
      method: "PUT",
      body: JSON.stringify({
        rating: Number($("#review-rating").value),
        content: $("#review-content").value.trim(),
        contains_spoiler: $("#review-spoiler").checked,
      }),
    });
    toast("Đã lưu review. Cảm ơn góc nhìn của bạn!");
    openMovie(id);
    loadMovies();
  } catch (error) {
    if ($("#review-error")) $("#review-error").textContent = error.message;
    if ($("#review-submit")) $("#review-submit").disabled = false;
  }
}

async function deleteReview(id) {
  if (!window.confirm("Xóa review của bạn về bộ phim này?")) return;
  try {
    await api(`/movies/${id}/reviews/me`, { method: "DELETE" });
    toast("Đã xóa review.");
    openMovie(id);
    loadMovies();
  } catch (error) {
    toast(error.message, true);
  }
}

function openChat() {
  $("#chat-panel").hidden = false;
  $("#chat-fab").hidden = true;
  if (!$("#chat-messages").children.length) resetChat();
  $("#chat-input").focus();
}

function closeChat() {
  $("#chat-panel").hidden = true;
  $("#chat-fab").hidden = false;
  $("#chat-fab").focus();
}

function appendMessage(text, role = "bot") {
  const node = document.createElement("div");
  node.className = `chat-message ${role}`;
  node.textContent = text;
  $("#chat-messages").append(node);
  $("#chat-messages").scrollTop = $("#chat-messages").scrollHeight;
  return node;
}

function resetChat() {
  ++state.chatVersion;
  state.chatHistory = [];
  state.chatPending = false;
  $("#chat-messages").replaceChildren();
  $("#chat-input").value = "";
  $("#chat-send").disabled = false;
  $("#chat-suggestions").hidden = false;
  appendMessage(
    "Chào bạn, mình là Ciné bot ✦\nBạn đang muốn xem một bộ phim như thế nào? Kể mình nghe thể loại, tâm trạng hoặc khoảng thời gian bạn có nhé.",
  );
  updateProviderLabel();
}

function updateProviderLabel() {
  const selected = state.providers.find((p) => p.id === state.provider);
  $("#chat-mode").textContent =
    state.provider === "auto"
      ? "Tự động chọn model theo cấu hình"
      : state.provider === "rules"
        ? "Bộ lọc từ khóa · Không dùng AI"
        : `${state.provider === "ollama" ? "Qwen local" : "Gemini"} · ${selected?.model || "Đang kiểm tra"}`;
  $("#provider-status").textContent =
    state.provider === "auto"
      ? "Ưu tiên theo AI_PROVIDER trong .env; nếu AI lỗi sẽ dùng bộ lọc."
      : selected?.message || "Chưa kiểm tra được kết nối. Nhấn ↺ để thử lại.";
}

async function refreshProviders(initial = false) {
  $("#refresh-providers").disabled = true;
  try {
    const data = await api("/ai/providers");
    state.providers = data.providers;
    if (initial && !state.providerTouched) {
      state.provider = data.default_provider;
      $("#chat-provider").value = state.provider;
    }
    updateProviderLabel();
  } catch (error) {
    $("#provider-status").textContent = error.message;
  } finally {
    $("#refresh-providers").disabled = false;
  }
}

async function sendChat(event) {
  event?.preventDefault();
  const message = $("#chat-input").value.trim();
  if (!message || state.chatPending) return;
  const version = state.chatVersion;
  state.chatPending = true;
  $("#chat-send").disabled = true;
  $("#chat-input").value = "";
  $("#chat-suggestions").hidden = true;
  appendMessage(message, "user");
  const thinking = appendMessage("Đang tìm câu chuyện dành cho bạn…");
  thinking.classList.add("chat-thinking");
  try {
    const result = await api("/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        history: state.chatHistory.slice(-6),
        provider: state.provider,
      }),
    });
    if (version !== state.chatVersion) return;
    thinking.remove();
    const node = appendMessage(result.reply);
    result.movies.forEach((movie) => {
      const button = document.createElement("button");
      button.className = "chat-result";
      button.innerHTML = `<img src="${imageURL(movie.poster_path, "w185")}" alt="" width="38" height="56"><span><strong>${esc(movie.title)} <span>↗</span></strong><small>${movieYear(movie)} · ${esc(movie.reason)}</small></span>`;
      button.addEventListener("click", () => openMovie(movie.tmdb_id));
      node.append(button);
    });
    const note = document.createElement("small");
    note.className = "chat-mode-note";
    note.textContent =
      result.mode === "ollama"
        ? `✦ Qwen local · ${result.model} · Xử lý trên máy qua Ollama`
        : result.mode === "gemini"
          ? `✦ Gemini · ${result.model} · Phim được kiểm tra từ database`
          : result.provider_notice ||
            "Đang dùng bộ lọc từ khóa · Không dùng AI";
    if (result.catalog_source === "cached")
      note.textContent += " · TMDB lỗi, dùng danh mục đã lưu";
    node.append(note);
    applyImageFallbacks(node);
    $("#chat-mode").textContent =
      result.mode === "ollama"
        ? "Qwen local · " + result.model
        : result.mode === "gemini"
          ? "Gemini · Gợi ý từ danh mục phim"
          : "Bộ lọc gợi ý theo từ khóa";
    // Keep only concise conversation text, never send movie cards or all catalog data.
    state.chatHistory.push(
      { role: "user", content: message },
      { role: "assistant", content: result.reply },
    );
    state.chatHistory = state.chatHistory.slice(-6);
  } catch (error) {
    if (version !== state.chatVersion) return;
    thinking.remove();
    appendMessage(error.message, "bot error");
  } finally {
    if (version === state.chatVersion) {
      state.chatPending = false;
      $("#chat-send").disabled = false;
      $("#chat-messages").scrollTop = $("#chat-messages").scrollHeight;
    }
  }
}

function bindEvents() {
  $("#account-button").addEventListener("click", () => openAuth());
  $("#login-tab").addEventListener("click", () => openAuth("login"));
  $("#register-tab").addEventListener("click", () => openAuth("register"));
  $("#auth-form").addEventListener("submit", submitAuth);
  $$("[data-close]").forEach((button) =>
    button.addEventListener("click", () =>
      document.getElementById(button.dataset.close).close(),
    ),
  );
  $$("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      const rect = dialog.getBoundingClientRect();
      if (
        event.target === dialog &&
        (event.clientX < rect.left ||
          event.clientX > rect.right ||
          event.clientY < rect.top ||
          event.clientY > rect.bottom)
      )
        dialog.close();
    });
  });
  $("#movie-dialog").addEventListener("close", () => {
    ++state.detailVersion;
    state.detail = null;
  });
  $("#logout-button").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await api("/auth/logout", { method: "POST" });
      updateUser(null);
      $("#auth-dialog").close();
      state.view = "explore";
      state.page = 1;
      loadMovies();
      if ($("#movie-dialog").open && state.detail)
        openMovie(state.detail.tmdb_id);
      toast("Đã đăng xuất.");
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
  $("#explore-nav").addEventListener("click", () => {
    state.view = "explore";
    state.page = 1;
    loadMovies();
  });
  $("#watchlist-nav").addEventListener("click", () => {
    if (!state.user) {
      openAuth();
      return;
    }
    state.view = "watchlist";
    state.page = 1;
    loadMovies({ scroll: true });
  });
  $$(".brand").forEach((a) =>
    a.addEventListener("click", (event) => {
      event.preventDefault();
      resetFilters();
      window.scrollTo({ top: 0, behavior: "smooth" });
    }),
  );
  $("#discover-button").addEventListener("click", () =>
    $("#catalog").scrollIntoView({ behavior: "smooth" }),
  );
  $("#hero-movie-button").addEventListener("click", () => openMovie(157336));
  ["chat-nav", "hero-chat-button", "banner-chat-button", "chat-fab"].forEach(
    (id) => $(`#${id}`).addEventListener("click", openChat),
  );
  $("#chat-close").addEventListener("click", closeChat);
  $("#chat-reset").addEventListener("click", resetChat);
  $("#refresh-providers").addEventListener("click", () => refreshProviders());
  $("#chat-provider").addEventListener("change", (event) => {
    state.providerTouched = true;
    state.provider = event.target.value;
    resetChat();
  });
  $("#chat-form").addEventListener("submit", sendChat);
  $$("#chat-suggestions button").forEach((button) =>
    button.addEventListener("click", () => {
      $("#chat-input").value = button.textContent;
      sendChat();
    }),
  );
  $("#genre-row").addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    if ("status" in button.dataset) state.status = button.dataset.status;
    else state.genre = button.dataset.genre;
    state.page = 1;
    loadMovies();
  });
  let searchTimer;
  $("#search-input").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.query = $("#search-input").value.trim();
      state.genre = "";
      state.page = 1;
      loadMovies();
    }, 350);
  });
  $("#year-filter").addEventListener("change", (event) => {
    state.year = event.target.value;
    state.page = 1;
    loadMovies();
  });
  $("#sort-filter").addEventListener("change", (event) => {
    state.sort = event.target.value;
    state.page = 1;
    loadMovies();
  });
  $("#reset-filters").addEventListener("click", resetFilters);
  $("#empty-reset").addEventListener("click", resetFilters);
  $("#prev-page").addEventListener("click", () => {
    state.page--;
    loadMovies({ scroll: true });
  });
  $("#next-page").addEventListener("click", () => {
    state.page++;
    loadMovies({ scroll: true });
  });
  $("#movie-grid").addEventListener("click", (event) => {
    const open = event.target.closest("[data-open-movie]");
    if (open) openMovie(Number(open.dataset.openMovie));
    const save = event.target.closest("[data-save-movie]");
    if (save) toggleSave(Number(save.dataset.saveMovie), save);
  });
  document.addEventListener("keydown", (event) => {
    if (
      event.key === "/" &&
      !["INPUT", "TEXTAREA", "SELECT"].includes(
        document.activeElement.tagName,
      ) &&
      !$$("dialog[open]").length
    ) {
      event.preventDefault();
      if (state.view === "watchlist") resetFilters();
      $("#search-input").focus();
    }
    if (
      event.key === "Escape" &&
      !$("#chat-panel").hidden &&
      !$$("dialog[open]").length
    )
      closeChat();
  });
}

async function init() {
  const year = new Date().getFullYear();
  $("#current-year").textContent = year;
  for (let y = year; y >= 1950; y--)
    $("#year-filter").insertAdjacentHTML(
      "beforeend",
      `<option value="${y}">${y}</option>`,
    );
  bindEvents();
  applyImageFallbacks();
  const [user, genres, health] = await Promise.allSettled([
    api("/auth/me"),
    api("/genres"),
    api("/health"),
  ]);
  if (user.status === "fulfilled") updateUser(user.value);
  if (genres.status === "fulfilled") state.genres = genres.value;
  if (health.status === "fulfilled") state.health = health.value;
  resetChat();
  refreshProviders(true);
  await loadMovies();
}

init().catch((error) => toast(error.message, true));
