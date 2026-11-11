"use strict";

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

