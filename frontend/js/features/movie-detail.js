"use strict";

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
      : '<span class="detail-cast">Chưa có trailer trong dữ liệu hiện tại.</span>';
    $("#movie-detail").innerHTML =
      `<div class="detail-cover">${movie.backdrop_path ? `<img src="${imageURL(movie.backdrop_path, "w1280")}" alt="Bối cảnh ${esc(movie.title)}">` : ""}</div>
      <div class="detail-body"><div class="detail-top"><img class="detail-poster" src="${imageURL(movie.poster_path)}" alt="Poster ${esc(movie.title)}" width="145" height="218"><div class="detail-info"><div class="eyebrow">MỖI BỘ PHIM, MỘT GÓC NHÌN</div><h2 id="detail-title">${esc(movie.title)}</h2><div class="detail-meta"><span>${movieYear(movie)}</span>${movie.runtime ? `<span>· ${movie.runtime} phút</span>` : ""}<span>· ${esc(movie.original_language.toUpperCase())}</span></div><div class="detail-genres">${movie.genres.map((g) => `<span>${esc(g)}</span>`).join("")}</div></div></div>
      <div class="detail-actions"><button class="button primary" id="detail-save">${movie.watchlist_status ? "✓ Đã lưu · Bỏ lưu" : "+ Thêm vào tủ phim"}</button><button class="button secondary" id="detail-watched">${movie.watchlist_status === "watched" ? "✓ Đã xem · Đánh dấu chưa xem" : "◎ Đánh dấu đã xem"}</button>${trailer}</div>
      ${movie.warning ? `<div class="notice">${esc(movie.warning)}</div>` : ""}
      <p class="detail-overview">${esc(movie.overview || "Chưa có tóm tắt cho bộ phim này.")}</p>${movie.cast_names?.length ? `<p class="detail-cast"><strong>Diễn viên</strong> &nbsp; ${movie.cast_names.map(esc).join(" · ")}</p>` : ""}
      <div class="rating-summary"><div><strong><span class="star">★</span> ${Number(movie.tmdb_rating).toFixed(1)}<span> / 10</span></strong><small>${state.health?.tmdb_configured ? "Điểm TMDB" : "Điểm TMDB · dữ liệu mẫu"}</small></div><div><strong>${movie.community_rating ?? "—"}<span> / 10</span></strong><small>Cộng đồng MovieMate · ${movie.review_count} review</small></div></div>
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

