"use strict";

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
