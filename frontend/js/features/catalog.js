"use strict";

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

