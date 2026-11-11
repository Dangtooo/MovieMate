"use strict";

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

