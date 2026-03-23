const API_BASE_URL = "http://localhost:8001";

// 401 gelince çağrılacak global callback — App.jsx'te set edilir
let _onUnauthorized = null;
export function setUnauthorizedHandler(fn) {
  _onUnauthorized = fn;
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, options);
  if (response.status === 401) {
    _onUnauthorized?.();
    const data = await safeJson(response);
    throw new Error(data.detail || "Oturum süresi doldu, tekrar giriş yapın");
  }
  return response;
}

export async function login(username, password) {
  const body = new URLSearchParams();
  body.append("username", username);
  body.append("password", password);
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const data = await safeJson(response);
  if (!response.ok) throw new Error(data.detail || "Giriş başarısız");
  return data;
}

export async function register(username, password) {
  const response = await fetch(`${API_BASE_URL}/users/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await safeJson(response);
  if (!response.ok) throw new Error(data.detail || "Kayıt başarısız");
  return data;
}

export async function getMe(token) {
  const response = await apiFetch(`${API_BASE_URL}/users/me`, {
    headers: getAuthHeaders(token),
  });
  const data = await safeJson(response);
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

export async function listConversations(token) {
  const response = await apiFetch(`${API_BASE_URL}/conversations/`, {
    headers: getAuthHeaders(token),
  });
  const data = await safeJson(response);
  if (!response.ok) throw new Error(data.detail || "Sohbetler alınamadı");
  return data;
}

export async function createConversation(token, title = "Yeni Sohbet") {
  const response = await apiFetch(`${API_BASE_URL}/conversations/`, {
    method: "POST",
    headers: { ...getAuthHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  const data = await safeJson(response);
  if (!response.ok) throw new Error(data.detail || "Sohbet oluşturulamadı");
  return data;
}

export async function deleteConversation(token, conversationId) {
  const response = await apiFetch(
    `${API_BASE_URL}/conversations/${conversationId}`,
    {
      method: "DELETE",
      headers: getAuthHeaders(token),
    },
  );
  if (!response.ok) {
    const data = await safeJson(response);
    throw new Error(data.detail || "Sohbet silinemedi");
  }
  return true;
}

export async function listMessages(token, conversationId) {
  const response = await apiFetch(
    `${API_BASE_URL}/messages/?conversation_id=${conversationId}`,
    { headers: getAuthHeaders(token) },
  );
  const data = await safeJson(response);
  if (!response.ok) throw new Error(data.detail || "Mesajlar alınamadı");
  return data;
}

export async function listDocuments(token, page = 1, pageSize = 100) {
  const response = await apiFetch(
    `${API_BASE_URL}/documents/?page=${page}&page_size=${pageSize}`,
    { headers: getAuthHeaders(token) },
  );
  const data = await safeJson(response);
  if (!response.ok) throw new Error(data.detail || "Belgeler alınamadı");
  return data;
}

export async function uploadDocument(token, file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await apiFetch(`${API_BASE_URL}/documents/ingest`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
  const data = await safeJson(response);
  if (!response.ok) throw new Error(data.detail || "Belge yüklenemedi");
  return data;
}

export async function uploadImageDocument(token, file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await apiFetch(`${API_BASE_URL}/documents/ingest-image`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
  const data = await safeJson(response);
  if (!response.ok) throw new Error(data.detail || "Görsel yüklenemedi");
  return data;
}

export async function uploadAnyDocument(token, file) {
  if (!file) throw new Error("Dosya seçilmedi");
  const isImage = file.type?.startsWith("image/");
  return isImage
    ? uploadImageDocument(token, file)
    : uploadDocument(token, file);
}

export async function listModels(token) {
  const response = await apiFetch(`${API_BASE_URL}/models/`, {
    headers: getAuthHeaders(token),
  });
  const data = await safeJson(response);
  if (!response.ok) throw new Error(data.detail || "Modeller alınamadı");
  return data;
}

export async function sendChat({
  token,
  conversationId,
  message,
  documentIds = [],
  model,
  temperature,
  imageFile,
}) {
  const formData = new FormData();
  formData.append("conversation_id", String(conversationId));
  formData.append("message", message);
  formData.append("document_ids", documentIds.join(","));
  if (model) formData.append("model", model);
  if (temperature !== undefined && temperature !== null)
    formData.append("temperature", String(temperature));
  if (imageFile) formData.append("image", imageFile);

  const response = await apiFetch(`${API_BASE_URL}/chat/`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
  const data = await safeJson(response);
  if (!response.ok) throw new Error(data.detail || "Mesaj gönderilemedi");
  return data;
}

export async function updateUsername(token, newUsername) {
  const response = await apiFetch(`${API_BASE_URL}/users/me/username`, {
    method: "PATCH",
    headers: { ...getAuthHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify({ new_username: newUsername }),
  });
  const data = await safeJson(response);
  if (!response.ok)
    throw new Error(
      data.detail || `Kullanıcı adı güncellenemedi (HTTP ${response.status})`,
    );
  return data;
}

export async function updatePassword(token, currentPassword, newPassword) {
  const response = await apiFetch(`${API_BASE_URL}/users/me/password`, {
    method: "PATCH",
    headers: { ...getAuthHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
  const data = await safeJson(response);
  if (!response.ok)
    throw new Error(
      data.detail || `Şifre güncellenemedi (HTTP ${response.status})`,
    );
  return data;
}

function getAuthHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}
