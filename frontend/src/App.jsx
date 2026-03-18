import { useEffect, useMemo, useRef, useState } from "react";
import {
  createConversation,
  deleteConversation,
  listConversations,
  listDocuments,
  listMessages,
  listModels,
  login,
  register,
  sendChat,
  uploadAnyDocument,
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
  const [selectedDocumentIds, setSelectedDocumentIds] = useState([]);
  const [modelData, setModelData] = useState(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedTemperature, setSelectedTemperature] =
    useState(DEFAULT_TEMPERATURE);
  const [prompt, setPrompt] = useState("");
  const [sending, setSending] = useState(false);
  const [uploadingDocument, setUploadingDocument] = useState(false);
  const [error, setError] = useState("");

  const mqttClientRef = useRef(null);
  const unsubscribeRef = useRef(null);
  const messagesEndRef = useRef(null);

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
      .replace(/\.md$/i, "")
      .trim();
  }

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

  function handleLogout() {
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
          <h3>Belgeler</h3>

          <div className="document-upload-box">
            <input
              type="file"
              accept=".pdf,.txt,.doc,.docx,.md,image/*"
              onChange={handleDocumentUpload}
              disabled={uploadingDocument}
            />
            {uploadingDocument && (
              <div className="hint-box">Belge yükleniyor...</div>
            )}
          </div>

          <div className="document-list">
            {documents.map((doc) => (
              <label key={doc.id} className="checkbox-item">
                <input
                  type="checkbox"
                  checked={selectedDocumentIds.includes(doc.id)}
                  onChange={() => toggleDocument(doc.id)}
                />
                <span>{formatDocumentName(doc)}</span>
              </label>
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
            <button type="submit" className="send-button" disabled={sending || !prompt.trim()} >
              {sending ? "Gönderiliyor..." : "Gönder"}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}