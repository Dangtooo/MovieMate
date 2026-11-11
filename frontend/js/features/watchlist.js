"use strict";

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
        ? "Đã xem! MovieMate bot sẽ tránh gợi ý lại phim này."
        : "Đã chuyển sang danh sách muốn xem.",
    );
    loadMovies();
    openMovie(id);
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

