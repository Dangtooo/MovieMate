"use strict";

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

