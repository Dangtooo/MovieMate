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
  chatSessionId: null,
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
  if (path === "/chat") {
    data.chatProvider = response.headers.get("X-Chat-Provider") || "gemini";
    data.chatAction = response.headers.get("X-Chat-Action") || "recommendations";
    data.chatNotice = decodeURIComponent(response.headers.get("X-Chat-Notice") || "");
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

