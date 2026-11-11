"use strict";

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
  state.chatSessionId = crypto.randomUUID();
  state.chatPending = false;
  $("#chat-messages").replaceChildren();
  $("#chat-input").value = "";
  $("#chat-send").disabled = false;
  $("#chat-suggestions").hidden = false;
  appendMessage(
    "Chào bạn, mình là MovieMate bot ✦\nBạn muốn xem gì? Mình có thể tìm theo nội dung, diễn viên/đạo diễn, phim tương tự hoặc phim đang/sắp chiếu. Bạn cũng có thể hỏi trailer và nơi xem của một phim.",
  );
  updateProviderLabel();
}

function updateProviderLabel() {
  const selected = state.providers.find((p) => p.id === "gemini");
  $("#chat-mode").textContent = "MovieMate · Gemini";
  $("#provider-status").textContent = selected?.ready
    ? "Sẵn sàng trò chuyện và tra cứu phim."
    : "Chatbot chưa sẵn sàng. Vui lòng thử lại sau.";
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

async function sendChat(event, selectedMovieId = null) {
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
        session_id: state.chatSessionId,
        provider: state.provider,
        selected_movie_id: selectedMovieId,
      }),
    });
    if (version !== state.chatVersion) return;
    thinking.remove();
    const node = appendMessage(result.reply);
    result.movies.forEach((movie) => {
      const card = document.createElement("div");
      card.className = "chat-movie-card";
      const button = document.createElement("button");
      button.className = "chat-result";
      const poster = /^https:\/\/image\.tmdb\.org\/t\/p\/w200\/[\w.-]+\.(jpg|png|webp)$/i.test(movie.poster_url || "")
        ? movie.poster_url : placeholder;
      button.innerHTML = `<img src="${poster}" alt="" width="44" height="66"><span><strong>${esc(movie.title)} <span>↗</span></strong><span class="chat-movie-meta">${esc(movie.release_year || "Chưa rõ năm")} <span class="chat-rating" aria-label="Điểm TMDB">★ ${Number(movie.rating).toFixed(1)}</span></span><small>${esc(movie.reason)}</small></span>`;
      button.addEventListener("click", () => openMovie(movie.id));
      card.append(button);
      if (result.chatAction === "choose-reference") {
        const choose = document.createElement("button");
        choose.className = "chat-choose-reference";
        choose.textContent = "Chọn phim này";
        choose.addEventListener("click", () => {
          if (state.chatPending || version !== state.chatVersion) return;
          $("#chat-input").value = `Chọn ${movie.title} (${movie.release_year || "chưa rõ năm"})`;
          sendChat(null, movie.id);
        });
        card.append(choose);
      }
      if (/^https:\/\/www\.youtube\.com\/watch\?v=[A-Za-z0-9_-]{11}$/.test(movie.trailer_url || "")) {
        const trailer = document.createElement("a");
        trailer.className = "chat-trailer-link";
        trailer.href = movie.trailer_url;
        trailer.target = "_blank";
        trailer.rel = "noopener noreferrer";
        trailer.textContent = "▶ Xem trailer chính thức";
        card.append(trailer);
      }
      node.append(card);
    });
    const note = document.createElement("small");
    note.className = "chat-mode-note";
    note.textContent = "✦ Gemini · Dữ liệu phim từ TMDB";
    node.append(note);
    applyImageFallbacks(node);
    $("#chat-mode").textContent = "MovieMate · Gemini";
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

