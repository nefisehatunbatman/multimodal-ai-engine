import { useEffect, useMemo, useRef, useState } from "react";
import {
  createConversation,
  deleteConversation,
  getMe,
  listConversations,
  listDocuments,
  listMessages,
  listModels,
  login,
  register,
  sendChat,
  setUnauthorizedHandler,
  uploadAnyDocument,
  updateUsername,
  updatePassword,
} from "./api";
import { createMqttClient, subscribeToChatStream } from "./mqtt";

const DEFAULT_TEMPERATURE = 0.2;

export default function App() {
  const [token, setToken] = useState(localStorage.getItem("token") || "");
  const [accountName, setAccountName] = useState(
    localStorage.getItem("username") || ""
  );
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authMode, setAuthMode] = useState("login");
  const [loadingAuth, setLoadingAuth] = useState(false);

  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState(() => {
    const uname = localStorage.getItem("username") || "";
    if (!uname) return [];
    try {
      const saved = localStorage.getItem(`selectedDocs_${uname}`);
      return saved ? JSON.parse(saved) : [];
    } catch { return []; }
  });
  const [modelData, setModelData] = useState(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedTemperature, setSelectedTemperature] =
    useState(DEFAULT_TEMPERATURE);
  const [prompt, setPrompt] = useState("");
  const [sending, setSending] = useState(false);
  const [uploadingDocument, setUploadingDocument] = useState(false);
  const [error, setError] = useState("");

  // Attachment panel state
  const [showAttachPanel, setShowAttachPanel] = useState(false);
  const [attachTab, setAttachTab] = useState("dokümanlar");
  const attachPanelRef = useRef(null);

  // Settings modal state
  const [showSettings, setShowSettings] = useState(false);
  const [settingsTab, setSettingsTab] = useState("hesap"); // "hesap" | "belgeler"
  const [newUsername, setNewUsername] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [settingsError, setSettingsError] = useState("");
  const [settingsSuccess, setSettingsSuccess] = useState("");
  const [savingSettings, setSavingSettings] = useState(false);

  const mqttClientRef = useRef(null);
  const unsubscribeRef = useRef(null);
  const messagesEndRef = useRef(null);

  // selectedDocumentIds degisince localStorage'a kaydet (kullanici bazli)
  useEffect(() => {
    if (!accountName) return;
    localStorage.setItem(`selectedDocs_${accountName}`, JSON.stringify(selectedDocumentIds));
  }, [selectedDocumentIds, accountName]);

  // Global 401 handler — token expire olunca otomatik logout
  useEffect(() => {
    const handler = () => {
      localStorage.removeItem("token");
      localStorage.removeItem("username");
      setToken("");
      setAccountName("");
      setConversations([]);
      setMessages([]);
      setDocuments([]);
      setModelData(null);
      setActiveConversationId(null);
      setSelectedDocumentIds([]);
      setPrompt("");
      setError("Oturum süreniz doldu, lütfen tekrar giriş yapın.");
    };
    setUnauthorizedHandler(handler);
    return () => setUnauthorizedHandler(null);
  }, []);

  // Close attach panel when clicking outside
  useEffect(() => {
    function handleClickOutside(e) {
      if (attachPanelRef.current && !attachPanelRef.current.contains(e.target)) {
        setShowAttachPanel(false);
      }
    }
    if (showAttachPanel) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showAttachPanel]);

  const categories = Array.isArray(modelData?.categories)
    ? modelData.categories
    : [];

  const temperaturePresets = Array.isArray(modelData?.temperature_presets)
    ? modelData.temperature_presets
    : [
        { label: "Düşük", value: 0.2 },
        { label: "Orta", value: 0.5 },
        { label: "Yüksek", value: 0.8 },
      ];

  const flatModels = useMemo(() => {
    return categories.flatMap((group) =>
      Array.isArray(group.models) ? group.models : []
    );
  }, [categories]);

  useEffect(() => {
    if (!token) return;

    const client = createMqttClient();
    mqttClientRef.current = client;

    return () => {
      unsubscribeRef.current?.();
      client.end(true);
      mqttClientRef.current = null;
    };
  }, [token]);

  useEffect(() => {
    if (!token) return;
    bootstrapApp();
  }, [token]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function formatDocumentName(doc) {
    const rawName = doc?.file_name || doc?.title || `Belge ${doc?.id ?? ""}`;
    return rawName
      .replace(/\s*\[hash:[^\]]+\]/gi, "")
      .replace(/\s*\[user:[^\]]+\]/gi, "")
      .replace(/\.md$/i, "")
      .trim();
  }

  // Categorize documents by type — 2 categories: dokümanlar & görseller
  const IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".gif", ".webp"];

  function getDocCategory(doc) {
    const name = (doc?.file_name || doc?.title || "").toLowerCase();
    if ((doc?.title || "").startsWith("Görsel:") || (doc?.file_name || "").startsWith("Görsel:")) return "görseller";
    const ext = name.match(/\.[^.]+$/)?.[0] || "";
    if (IMAGE_EXTS.includes(ext)) return "görseller";
    return "dokümanlar";
  }

  const categorizedDocs = {
    dokümanlar: documents.filter((d) => getDocCategory(d) === "dokümanlar"),
    görseller: documents.filter((d) => getDocCategory(d) === "görseller"),
  };

  async function bootstrapApp() {
    try {
      setError("");

      const [conversationList, documentResult, modelResult] = await Promise.all([
        listConversations(token),
        listDocuments(token, 1, 100),
        listModels(token),
      ]);

      const safeConversations = Array.isArray(conversationList)
        ? conversationList
        : [];

      const safeDocuments = Array.isArray(documentResult)
        ? documentResult
        : Array.isArray(documentResult?.documents)
        ? documentResult.documents
        : [];

      setConversations(safeConversations);
      setDocuments(safeDocuments);
      setModelData(modelResult || null);
      // YENİ

      const firstModel =
          modelResult?.categories
          ?.flatMap((g) => g.models ?? [])
          ?.find((m) => m.id === "openai/gpt-4o-mini")?.id
          ?? modelResult?.categories?.[0]?.models?.[0]?.id
          ?? "";

        setSelectedModel(firstModel);

  
      if (safeConversations.length > 0) {
        const firstConversationId = safeConversations[0].id;
        setActiveConversationId(firstConversationId);

        const messageList = await listMessages(token, firstConversationId);
        setMessages(Array.isArray(messageList) ? messageList : []);
      } else {
        const newConversation = await createConversation(token);
        setConversations([newConversation]);
        setActiveConversationId(newConversation.id);
        setMessages([]);
      }
    } catch (err) {
      setError(err.message || "Uygulama yüklenemedi");
    }
  }

  async function handleAuthSubmit(e) {
    e.preventDefault();
    setLoadingAuth(true);
    setError("");

    try {
      if (authMode === "register") {
        await register(username, password);
      }

      const result = await login(username, password);
      localStorage.setItem("token", result.access_token);
      localStorage.setItem("username", username);

      setToken(result.access_token);
      setAccountName(username);
      try {
        const saved = localStorage.getItem(`selectedDocs_${username}`);
        setSelectedDocumentIds(saved ? JSON.parse(saved) : []);
      } catch { setSelectedDocumentIds([]); }
      setUsername("");
      setPassword("");
    } catch (err) {
      setError(err.message || "Kimlik doğrulama başarısız");
    } finally {
      setLoadingAuth(false);
    }
  }

  async function handleSelectConversation(conversationId) {
    try {
      setError("");
      setActiveConversationId(conversationId);

      const data = await listMessages(token, conversationId);
      setMessages(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || "Mesajlar alınamadı");
    }
  }

  async function handleNewConversation() {
    try {
      setError("");
      const newConversation = await createConversation(token);
      setConversations((prev) => [newConversation, ...prev]);
      setActiveConversationId(newConversation.id);
      setMessages([]);
    } catch (err) {
      setError(err.message || "Yeni sohbet oluşturulamadı");
    }
  }

  async function handleDeleteConversation(conversationId) {
    try {
      setError("");
      await deleteConversation(token, conversationId);

      const nextConversations = conversations.filter(
        (item) => item.id !== conversationId
      );
      setConversations(nextConversations);

      if (activeConversationId === conversationId) {
        if (nextConversations.length > 0) {
          const nextId = nextConversations[0].id;
          setActiveConversationId(nextId);

          const data = await listMessages(token, nextId);
          setMessages(Array.isArray(data) ? data : []);
        } else {
          const newConversation = await createConversation(token);
          setConversations([newConversation]);
          setActiveConversationId(newConversation.id);
          setMessages([]);
        }
      }
    } catch (err) {
      setError(err.message || "Sohbet silinemedi");
    }
  }

  function toggleDocument(documentId) {
    setSelectedDocumentIds((prev) => {
      if (prev.includes(documentId)) {
        return prev.filter((id) => id !== documentId);
      }
      return [...prev, documentId];
    });
  }

  async function handleDocumentUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setUploadingDocument(true);
      setError("");

      await uploadAnyDocument(token, file);

      const refreshedDocuments = await listDocuments(token, 1, 100);

      const safeDocuments = Array.isArray(refreshedDocuments)
        ? refreshedDocuments
        : Array.isArray(refreshedDocuments?.documents)
        ? refreshedDocuments.documents
        : [];

      setDocuments(safeDocuments);
    } catch (err) {
      setError(err.message || "Belge yüklenemedi");
    } finally {
      setUploadingDocument(false);
      e.target.value = "";
    }
  }

  async function handleSendMessage(e) {
    e.preventDefault();

    if (!prompt.trim() || !activeConversationId || sending) {
      return;
    }

    setSending(true);
    setError("");

    const currentPrompt = prompt;

    const tempUserMessage = {
      id: `temp-user-${Date.now()}`,
      role: "user",
      content: currentPrompt,
    };

    const tempAssistantId = `temp-assistant-${Date.now()}`;
    const tempAssistantMessage = {
      id: tempAssistantId,
      role: "assistant",
      content: "",
      meta: { status: "streaming" },
    };

    setMessages((prev) => [...prev, tempUserMessage, tempAssistantMessage]);
    setPrompt("");

    try {
      unsubscribeRef.current?.();

      const result = await sendChat({
        token,
        conversationId: activeConversationId,
        message: currentPrompt,
        documentIds: selectedDocumentIds,
        model: selectedModel,
        temperature: selectedTemperature,
      });

      if (!mqttClientRef.current) {
        throw new Error("MQTT bağlantısı kurulamadı");
      }

      unsubscribeRef.current = subscribeToChatStream({
        client: mqttClientRef.current,
        streamTopic: result.stream_topic,
        doneTopic: result.done_topic,
        onToken: (tokenPart) => {
          if (!tokenPart) return;
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === tempAssistantId
                ? { ...msg, content: msg.content + tokenPart }
                : msg
            )
          );
        },
        onDone: async (payload) => {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === tempAssistantId
                ? {
                    ...msg,
                    content: payload.full_text || msg.content,
                    meta: {
                      ...(msg.meta || {}),
                      ...(payload.meta || {}),
                      status: "completed",
                    },
                  }
                : msg
            )
          );

          try {
            const refreshedMessages = await listMessages(
              token,
              activeConversationId
            );
            setMessages(Array.isArray(refreshedMessages) ? refreshedMessages : []);

            const refreshedConversations = await listConversations(token);
            setConversations(
              Array.isArray(refreshedConversations) ? refreshedConversations : []
            );
          } finally {
            setSending(false);
          }
        },
        onError: (err) => {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === tempAssistantId
                ? {
                    ...msg,
                    content: "Bir hata oluştu.",
                    meta: { ...(msg.meta || {}), status: "failed" },
                  }
                : msg
            )
          );

          setError(err.message || "Streaming sırasında hata oluştu");
          setSending(false);
        },
      });
    } catch (err) {
      setError(err.message || "Mesaj gönderilemedi");
      setSending(false);
    }
  }

  async function handleUpdateUsername(e) {
    e.preventDefault();
    if (!newUsername.trim()) return;
    setSavingSettings(true);
    setSettingsError("");
    setSettingsSuccess("");
    try {
      const oldName = accountName;
      await updateUsername(token, newUsername.trim());
      // Belge seçimlerini yeni kullanıcı adı key'ine taşı
      const saved = localStorage.getItem(`selectedDocs_${oldName}`);
      if (saved) {
        localStorage.setItem(`selectedDocs_${newUsername.trim()}`, saved);
        localStorage.removeItem(`selectedDocs_${oldName}`);
      }
      localStorage.setItem("username", newUsername.trim());
      setAccountName(newUsername.trim());
      setSettingsSuccess("Kullanıcı adı güncellendi!");
      setNewUsername("");
    } catch (err) {
      setSettingsError(err.message || "Güncelleme başarısız");
    } finally {
      setSavingSettings(false);
    }
  }

  async function handleUpdatePassword(e) {
    e.preventDefault();
    if (!currentPassword || !newPassword) return;
    if (newPassword !== confirmPassword) {
      setSettingsError("Yeni şifreler eşleşmiyor");
      return;
    }
    setSavingSettings(true);
    setSettingsError("");
    setSettingsSuccess("");
    try {
      await updatePassword(token, currentPassword, newPassword);
      setSettingsSuccess("Şifre güncellendi!");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setSettingsError(err.message || "Şifre güncellenemedi");
    } finally {
      setSavingSettings(false);
    }
  }

  function handleOpenSettings() {
    setSettingsError("");
    setSettingsSuccess("");
    setNewUsername(accountName); // mevcut adı pre-fill et
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setSettingsTab("hesap");
    setShowSettings(true);
  }

  function handleLogout() {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    // selectedDocs_<username> kasıtlı silinmiyor — sonraki girişte geri yüklenir
    setToken("");
    setAccountName("");
    setConversations([]);
    setMessages([]);
    setDocuments([]);
    setModelData(null);
    setActiveConversationId(null);
    setSelectedDocumentIds([]);
    setPrompt("");
    setError("");
  }

  if (!token) {
    return (
      <div className="auth-page">
        <form className="auth-card" onSubmit={handleAuthSubmit}>
          <h1>AI Engine</h1>
          <p>Hoşgeldiniz!</p>

          <input
            type="text"
            placeholder="Kullanıcı adı"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />

          <input
            type="password"
            placeholder="Şifre"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          <button type="submit" disabled={loadingAuth}>
            {loadingAuth
              ? "Bekleyin..."
              : authMode === "login"
              ? "Giriş Yap"
              : "Kayıt Ol"}
          </button>

          <button
            type="button"
            className="ghost-button"
            onClick={() =>
              setAuthMode((prev) => (prev === "login" ? "register" : "login"))
            }
          >
            {authMode === "login"
              ? "Hesabın yok mu? Kayıt ol"
              : "Zaten hesabın var mı? Giriş yap"}
          </button>

          {error && <div className="error-box">{error}</div>}
        </form>
      </div>
    );
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-section account-section">
          <div className="account-card">
            <div className="account-avatar">
              {(accountName || "U").charAt(0).toUpperCase()}
            </div>
            <div className="account-info">
              <div className="account-label">Hesap</div>
              <div className="account-name">{accountName || "Kullanıcı"}</div>
            </div>
            <button className="ghost-button logout-button" onClick={handleLogout}>
              Çıkış
            </button>
            <button className="ghost-button settings-button" onClick={handleOpenSettings} title="Ayarlar">
              ⚙️
            </button>
          </div>
        </div>

        <div className="sidebar-section">
          <button onClick={handleNewConversation}>+ Yeni Sohbet</button>
        </div>

        <div className="sidebar-section">
          <h3>Sohbetler</h3>
          <div className="conversation-list">
            {conversations.map((conv) => (
              <div
                key={conv.id}
                className={`conversation-item ${
                  conv.id === activeConversationId ? "active" : ""
                }`}
              >
                <button onClick={() => handleSelectConversation(conv.id)}>
                  {conv.title || `Sohbet ${conv.id}`}
                </button>

                <button
                  className="delete-button"
                  onClick={() => handleDeleteConversation(conv.id)}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="sidebar-section">
          <h3>Model</h3>
          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
          >
            <option value="">Model seç</option>

            {categories.length > 0
              ? categories.map((group, index) => (
                  <optgroup
                    key={group.category || index}
                    label={group.category || `Kategori ${index + 1}`}
                  >
                    {(Array.isArray(group.models) ? group.models : []).map(
                      (model) => (
                        <option key={model.id} value={model.id}>
                          {model.name || model.id}
                          {model.provider ? ` - ${model.provider}` : ""}
                        </option>
                      )
                    )}
                  </optgroup>
                ))
              : null}
          </select>

          <h3>Yaratıcılık</h3>
          <select
            value={selectedTemperature}
            onChange={(e) => setSelectedTemperature(Number(e.target.value))}
          >
            {temperaturePresets.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label} ({item.value})
              </option>
            ))}
          </select>

          <div className="hint-box">
            Seçili model:{" "}
            {flatModels.find((model) => model.id === selectedModel)?.name ||
              selectedModel ||
              "-"}
          </div>
        </div>
      </aside>

      <main className="chat-panel">
        <div className="chat-header">
          <h2>Chat</h2>
          <span>{selectedDocumentIds.length} belge seçili</span>
        </div>

        <div className="message-list">
          {messages.map((msg) => (
            <div key={msg.id} className={`message ${msg.role || "assistant"}`}>
              <div className="message-role">
                {msg.role === "user" ? "Sen" : "Asistan"}
              </div>
              <div className="message-content">{msg.content || ""}</div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {error && <div className="error-box chat-error">{error}</div>}

        <form className="composer" onSubmit={handleSendMessage}>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Mesajını yaz..."
            rows={4}
          />

          <div className="composer-footer">
            {/* Attach panel anchor */}
            <div className="attach-wrapper" ref={attachPanelRef}>
              <button
                type="button"
                className={`attach-button ${showAttachPanel ? "active" : ""}`}
                onClick={() => setShowAttachPanel((p) => !p)}
                title="Dosya ekle"
              >
                +
                {selectedDocumentIds.length > 0 && (
                  <span className="attach-badge">{selectedDocumentIds.length}</span>
                )}
              </button>

              {showAttachPanel && (
                <div className="attach-panel">
                  <div className="attach-panel-header">
                    <span>Dosya Ekle</span>
                    <button
                      type="button"
                      className="attach-panel-close"
                      onClick={() => setShowAttachPanel(false)}
                    >
                      ×
                    </button>
                  </div>

                  {/* Tabs */}
                  <div className="attach-tabs">
                    {["dokümanlar", "görseller"].map((tab) => (
                      <button
                        key={tab}
                        type="button"
                        className={`attach-tab ${attachTab === tab ? "active" : ""}`}
                        onClick={() => setAttachTab(tab)}
                      >
                        {tab === "dokümanlar" && "Dokümanlar"}
                        {tab === "görseller" && "Görseller"}
                        {categorizedDocs[tab].length > 0 && (
                          <span className="tab-count">{categorizedDocs[tab].length}</span>
                        )}
                      </button>
                    ))}
                  </div>

                  {/* Upload area */}
                  <div className="attach-upload">
                    <label className={`upload-label ${uploadingDocument ? "loading" : ""}`}>
                      <input
                        type="file"
                        accept={
                          attachTab === "görseller"
                            ? "image/*"
                            : ".pdf,.txt,.doc,.docx,.md"
                        }
                        onChange={handleDocumentUpload}
                        disabled={uploadingDocument}
                        style={{ display: "none" }}
                      />
                      {uploadingDocument ? "Yükleniyor..." : "+ Yeni dosya yükle"}
                    </label>
                  </div>

                  {/* File list */}
                  <div className="attach-list">
                    {categorizedDocs[attachTab].length === 0 ? (
                      <div className="attach-empty">Bu kategoride dosya yok</div>
                    ) : (
                      categorizedDocs[attachTab].map((doc) => (
                        <label key={doc.id} className="attach-item">
                          <input
                            type="checkbox"
                            checked={selectedDocumentIds.includes(doc.id)}
                            onChange={() => toggleDocument(doc.id)}
                          />
                          <span className="attach-item-name">{formatDocumentName(doc)}</span>
                        </label>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            <button type="submit" className="send-button" disabled={sending || !prompt.trim()}>
              {sending ? "Gönderiliyor..." : "Gönder"}
            </button>
          </div>
        </form>
      </main>

      {/* Settings Modal */}
      {showSettings && (
        <div className="modal-overlay" onClick={() => setShowSettings(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Ayarlar</h3>
              <button className="modal-close" onClick={() => setShowSettings(false)}>×</button>
            </div>

            {/* Modal Tabs */}
            <div className="modal-tabs">
              <button
                className={`modal-tab ${settingsTab === "hesap" ? "active" : ""}`}
                onClick={() => { setSettingsTab("hesap"); setSettingsError(""); setSettingsSuccess(""); }}
              >
                 Hesap
              </button>
              <button
                className={`modal-tab ${settingsTab === "belgeler" ? "active" : ""}`}
                onClick={() => { setSettingsTab("belgeler"); setSettingsError(""); setSettingsSuccess(""); }}
              >
                 Varsayılan Belgeler
              </button>
            </div>

            <div className="modal-body">
              {settingsError && <div className="settings-error">{settingsError}</div>}
              {settingsSuccess && <div className="settings-success">{settingsSuccess}</div>}

              {settingsTab === "hesap" && (
                <div className="settings-section">
                  {/* Username update */}
                  <div className="settings-group">
                    <h4>Kullanıcı Adını Değiştir</h4>
                    <form onSubmit={handleUpdateUsername}>
                      <input
                        type="text"
                        placeholder={`Mevcut: ${accountName}`}
                        value={newUsername}
                        onChange={(e) => setNewUsername(e.target.value)}
                      />
                      <button type="submit" disabled={savingSettings || !newUsername.trim()}>
                        {savingSettings ? "Kaydediliyor..." : "Güncelle"}
                      </button>
                    </form>
                  </div>

                  {/* Password update */}
                  <div className="settings-group">
                    <h4>Şifre Değiştir</h4>
                    <form onSubmit={handleUpdatePassword}>
                      <input
                        type="password"
                        placeholder="Mevcut şifre"
                        value={currentPassword}
                        onChange={(e) => setCurrentPassword(e.target.value)}
                      />
                      <input
                        type="password"
                        placeholder="Yeni şifre"
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                      />
                      <input
                        type="password"
                        placeholder="Yeni şifre (tekrar)"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                      />
                      <button
                        type="submit"
                        disabled={savingSettings || !currentPassword || !newPassword || !confirmPassword}
                      >
                        {savingSettings ? "Kaydediliyor..." : "Şifreyi Güncelle"}
                      </button>
                    </form>
                  </div>
                </div>
              )}

              {settingsTab === "belgeler" && (
                <div className="settings-section">
                  <p className="settings-hint">
                    Aşağıdan seçtiğiniz belgeler tüm sohbetlerde varsayılan olarak aktif olacak.
                  </p>

                  {/* Category tabs inside settings */}
                  <div className="attach-tabs" style={{ marginBottom: 8 }}>
                    {["dokümanlar", "görseller"].map((tab) => (
                      <button
                        key={tab}
                        type="button"
                        className={`attach-tab ${attachTab === tab ? "active" : ""}`}
                        onClick={() => setAttachTab(tab)}
                      >
                        {tab === "dokümanlar" && "Dokümanlar"}
                        {tab === "görseller" && "Görseller"}
                        {categorizedDocs[tab].length > 0 && (
                          <span className="tab-count">{categorizedDocs[tab].length}</span>
                        )}
                      </button>
                    ))}
                  </div>

                  <div className="settings-doc-list">
                    {categorizedDocs[attachTab].length === 0 ? (
                      <div className="attach-empty">Bu kategoride dosya yok</div>
                    ) : (
                      categorizedDocs[attachTab].map((doc) => (
                        <label key={doc.id} className="attach-item">
                          <input
                            type="checkbox"
                            checked={selectedDocumentIds.includes(doc.id)}
                            onChange={() => toggleDocument(doc.id)}
                          />
                          <span className="attach-item-name">{formatDocumentName(doc)}</span>
                        </label>
                      ))
                    )}
                  </div>

                  <div className="settings-hint" style={{ marginTop: 10 }}>
                    {selectedDocumentIds.length} belge seçili
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}