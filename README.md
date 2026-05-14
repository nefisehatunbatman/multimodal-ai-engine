# Multimodal AI Knowledge Engine

**RAG, Vision & Real-Time Messaging mimarisini birleştiren kurumsal yapay zeka motoru.**

Hem metinsel (PDF, DOCX, TXT) hem de görsel verileri anlayan, indeksleyen ve bu verilerle gerçek zamanlı konuşmaya olanak tanıyan bir FastAPI monoliti.

---


## İçindekiler

- [Mimari Genel Bakış](#mimari-genel-bakış)
- [Sistem Bileşenleri](#sistem-bileşenleri)
- [Kurulum](#kurulum)
- [Ortam Değişkenleri](#ortam-değişkenleri)
- [API Referansı](#api-referansı)
- [Teknik Kararlar ve Gerekçeler](#teknik-kararlar-ve-gerekçeler)

---

## Mimari Genel Bakış

```
┌─────────────────────────────────────────────────────────┐
│                      React Frontend                      │
│          (Vite + MQTT.js WebSocket istemcisi)            │
└───────────────────┬─────────────────┬───────────────────┘
                    │ REST             │ MQTT (WebSocket)
                    ▼                 ▼
┌───────────────────────────────────────────────────────────┐
│                    FastAPI (Port 8001)                     │
│  /auth  /users  /conversations  /messages                 │
│  /documents  /chat  /models  /health                      │
└──┬──────────────┬──────────────┬──────────────┬──────────┘
   │              │              │              │
   ▼              ▼              ▼              ▼
PostgreSQL    EMQX Broker    WeKnora App    OpenRouter API
(Kullanıcı,  (MQTT Broker,  (RAG + Qdrant  (LLM + Vision)
 Sohbet,      Port 1883/     Hibrit Arama,
 Mesajlar)    8083 WS)       Port 8080)
                                  │
                              Qdrant
                           (Vektör DB,
                            Port 6333)
```

**Temel Akış:**

1. Kullanıcı mesaj gönderir → FastAPI `/chat/` endpoint'i tetiklenir
2. FastAPI, WeKnora'da hibrit arama (vektör + keyword) yapar → ilgili chunk'lar alınır
3. Chunk'lar + mesaj geçmişi → OpenRouter üzerinden seçili LLM'e gönderilir
4. LLM yanıtı token token MQTT üzerinden yayınlanır → Frontend anlık gösterir
5. Konuşma tamamlandığında mesajlar PostgreSQL'e kaydedilir

---

## Sistem Bileşenleri

### PostgreSQL

Kullanıcı bilgileri, sohbet geçmişi ve mesaj meta verileri burада tutulur. Mesajlardaki model adı, token kullanımı, yanıt süresi gibi yapılandırılmamış veriler `JSONB` alanında saklanır; böylece şema değişikliği gerekmeden esnek metadata depolanabilir.

### EMQX (MQTT Broker)

LLM yanıtlarının token token (`streaming`) iletilmesi için kullanılır. Her sohbet mesajına özgü topic'ler oluşturulur:

- `ai/chat/{conversation_id}/{message_id}/stream` → anlık token akışı
- `ai/chat/{conversation_id}/{message_id}/done` → tamamlanma sinyali

Frontend MQTT.js ile WebSocket üzerinden (`ws://localhost:8083`) bu topic'lere abone olur.

### WeKnora (RAG Motoru)

Tencent/WeKnora, belge işleme (parse → chunk) ve hibrit arama (vektör + BM25 keyword) katmanını sağlar. Yüklenen belgeler WeKnora tarafından otomatik işlenerek Qdrant'a embed edilir. Arama sırasında LLM ile query expansion uygulanarak semantik kapsam genişletilir.

### Qdrant (Vektör Veritabanı)

WeKnora tarafından yönetilen embedding'lerin depolandığı ve similarity search'ün yürütüldüğü katmandır. WeKnora → Qdrant entegrasyonu `docker-compose.yml` içindeki ağ yapılandırmasıyla otomatik kurulur.

### OpenRouter (LLM & Vision Orkestrasyonu)

Tüm model çağrıları tek noktadan (OpenRouter) yönetilir. Ücretsizden premium'a geniş model kataloğu sunar; model ve sıcaklık ayarları kullanıcı tarafından konuşma başına seçilebilir.

**Kullanılan modeller ve tercih gerekçeleri:**

| Model                                   | Kullanım Amacı                  | Tercih Gerekçesi                      |
| --------------------------------------- | ------------------------------- | ------------------------------------- |
| `openai/gpt-4o-mini`                    | Varsayılan sohbet & vision      | Fiyat/performans dengesi, hızlı yanıt |
| `openai/gpt-4o`                         | Güçlü analiz & görsel anlama    | En yüksek doğruluk, multimodal        |
| `anthropic/claude-sonnet-4-6`           | Kod ve uzun doküman analizi     | 200K context, yüksek kalite           |
| `google/gemini-flash-1.5`               | Çok sayıda görsel / uzun bağlam | 1M token context, ekonomik            |
| `meta-llama/llama-3.1-8b-instruct:free` | Geliştirme & test               | Ücretsiz, hızlı prototipleme          |

---

## Kurulum

### Gereksinimler

- Docker & Docker Compose
- OpenRouter API anahtarı ([openrouter.ai](https://openrouter.ai))

### 1. Repoyu klonlayın

```bash
git clone <repo-url>
cd <proje-klasörü>
```

### 2. Ortam değişkenlerini ayarlayın

```bash
cp .env.example .env
# .env dosyasını düzenleyin (aşağıdaki tabloya bakın)
```

### 3. WeKnora skill klasörünü oluşturun

```bash
mkdir -p WeKnora/skills/preloaded
```

### 4. Tüm servisleri başlatın

```bash
docker compose up -d --build
```

### 5. Sağlık kontrolü

```bash
# Tüm container'ların ayakta olduğunu doğrulayın
docker compose ps

# FastAPI'nin çalıştığını kontrol edin
curl http://localhost:8001/health/weknora
```

### 6. WeKnora'da Knowledge Base oluşturun

WeKnora arayüzüne `http://localhost:3080` adresinden giriş yapın, bir Knowledge Base oluşturun ve ID'sini `.env` dosyasındaki `WEKNORA_KB_ID` değişkenine yazın.

### 7. Frontend'i başlatın (geliştirme)

```bash
cd frontend
npm install
npm run dev
# http://localhost:5173
```

---

## Ortam Değişkenleri

| Değişken                   | Açıklama                       | Örnek                      |
| -------------------------- | ------------------------------ | -------------------------- |
| `DB_USER`                  | PostgreSQL kullanıcısı         | `postgres`                 |
| `DB_PASSWORD`              | PostgreSQL şifresi             | `secret`                   |
| `DB_NAME`                  | Veritabanı adı                 | `ai_engine`                |
| `DB_HOST`                  | DB host (docker içi)           | `postgres_db`              |
| `DB_PORT`                  | DB port                        | `5432`                     |
| `SECRET_KEY`               | JWT imzalama anahtarı          | rastgele 32 karakter       |
| `OPENROUTER_API_KEY`       | OpenRouter API anahtarı        | `sk-or-...`                |
| `OPENROUTER_MODEL_PRIMARY` | Varsayılan LLM                 | `openai/gpt-4o-mini`       |
| `OPENROUTER_VISION_MODEL`  | Görsel analiz modeli           | `openai/gpt-4o-mini`       |
| `WEKNORA_APP_HOST`         | WeKnora container adı          | `WeKnora-app`              |
| `WEKNORA_APP_PORT`         | WeKnora portu                  | `8080`                     |
| `WEKNORA_API_KEY`          | WeKnora API anahtarı           | WeKnora arayüzünden alınır |
| `WEKNORA_KB_ID`            | Knowledge Base ID              | WeKnora arayüzünden alınır |
| `WEKNORA_DB_USER`          | WeKnora PostgreSQL kullanıcısı | `weknora`                  |
| `WEKNORA_DB_PASSWORD`      | WeKnora PostgreSQL şifresi     | `secret`                   |
| `WEKNORA_DB_NAME`          | WeKnora veritabanı adı         | `weknora`                  |
| `WEKNORA_REDIS_PASSWORD`   | Redis şifresi                  | `secret`                   |
| `WEKNORA_JWT_SECRET`       | WeKnora JWT anahtarı           | rastgele 32 karakter       |
| `WEKNORA_TENANT_AES_KEY`   | WeKnora AES anahtarı           | 32 byte hex                |
| `WEKNORA_SYSTEM_AES_KEY`   | WeKnora sistem AES             | 32 byte hex                |
| `MQTT_HOST`                | EMQX container adı             | `emqx`                     |
| `MQTT_PORT`                | MQTT portu                     | `1883`                     |
| `MAX_FILE_SIZE_MB`         | Maksimum dosya boyutu          | `50`                       |

---

## API Referansı

Tüm endpoint'ler `http://localhost:8001` üzerinde çalışır. Swagger dokümantasyonu: `http://localhost:8001/docs`

### Kimlik Doğrulama

| Method | Endpoint      | Açıklama               |
| ------ | ------------- | ---------------------- |
| `POST` | `/users/`     | Yeni kullanıcı kaydı   |
| `POST` | `/auth/login` | Giriş, JWT token döner |

### Sohbetler

| Method   | Endpoint                    | Açıklama                          |
| -------- | --------------------------- | --------------------------------- |
| `GET`    | `/conversations/`           | Kullanıcının sohbetlerini listele |
| `POST`   | `/conversations/`           | Yeni sohbet oluştur               |
| `PATCH`  | `/conversations/{id}/title` | Başlık güncelle                   |
| `DELETE` | `/conversations/{id}`       | Sohbet sil                        |

### Mesajlar & Chat

| Method | Endpoint                       | Açıklama                          |
| ------ | ------------------------------ | --------------------------------- |
| `GET`  | `/messages/?conversation_id=X` | Mesajları listele                 |
| `POST` | `/chat/`                       | Mesaj gönder (streaming başlatır) |

`/chat/` endpoint'i `multipart/form-data` kabul eder: `conversation_id`, `message`, `document_ids` (virgülle ayrılmış), `model`, `temperature`, `image` (opsiyonel görsel).

Yanıt olarak MQTT topic bilgisi döner; frontend bu topic'lere abone olarak token akışını alır.

### Belgeler

| Method | Endpoint                  | Açıklama                             |
| ------ | ------------------------- | ------------------------------------ |
| `GET`  | `/documents/`             | KB'deki belgeleri listele            |
| `POST` | `/documents/ingest`       | PDF/DOCX/TXT yükle                   |
| `POST` | `/documents/ingest-image` | Görsel yükle (LLM ile analiz edilir) |

### Diğer

| Method | Endpoint          | Açıklama                              |
| ------ | ----------------- | ------------------------------------- |
| `GET`  | `/models/`        | Model kataloğu ve sıcaklık presetleri |
| `GET`  | `/health/weknora` | WeKnora sağlık kontrolü               |

---

## Teknik Kararlar ve Gerekçeler

### Neden JSONB?

Mesaj meta verileri (token sayısı, model adı, yanıt süresi, chunk kaynakları) zamanla değişen ve öngörülemeyen bir yapıya sahiptir. Her meta veri türü için ayrı sütun açmak hem şema yönetimini zorlaştırır hem de migration maliyeti doğurur.

`JSONB` ile bu veriler tek sütunda esnek biçimde saklanır; üstelik PostgreSQL `JSONB` üzerinde GIN index desteklediğinden belirli alanlara göre sorgulama performanslı şekilde yapılabilir. Bu esneklik, modelden modele değişen metadata yapılarını (bazı modeller `reasoning_tokens` döndürür, bazıları döndürmez) tek şema ile yönetmeyi mümkün kılar.

### Neden MQTT / EMQX?

LLM yanıtları `token-by-token` gelir; bu yanıtları kullanıcıya gerçek zamanlı iletmek için iki temel seçenek vardır: **Server-Sent Events (SSE)** ve **MQTT**.

SSE, HTTP bağlantısını açık tutar; ölçeklendiğinde her kullanıcı için sunucuda açık bir bağlantı demektir. MQTT ise publish/subscribe modeliyle çalışır: FastAPI sadece topic'e yayınlar, EMQX broker dağıtımı üstlenir. Bu ayrışma sayesinde FastAPI ve frontend birbirinden bağımsız ölçeklenebilir.

EMQX'in WebSocket desteği (`port 8083`) frontend'in herhangi bir ek altyapı olmadan tarayıcıdan doğrudan MQTT'ye bağlanmasını sağlar. `retain=True` flag'i ile `done` mesajı saklanır; geç bağlanan istemciler bile tamamlanma sinyalini kaçırmaz.

### Neden WeKnora + Qdrant?

Saf vektör araması, semantik benzerlik konusunda güçlüdür ancak tam kelime eşleşmesi (özel isimler, kodlar, teknik terimler) konusunda zayıf kalabilir. WeKnora'nın **hibrit arama** motoru, Qdrant'ın vektör aramasını BM25 tabanlı keyword aramasıyla birleştirir; her iki yaklaşımın avantajını tek sorguda sunar.

Buna ek olarak sistemde **query expansion** uygulanmaktadır: kullanıcının sorusu LLM ile semantik olarak genişletilir (örn. "toplam maliyet" → "toplam maliyet, toplam gider, finansal özet"), ardından genişletilmiş sorgu WeKnora'ya gönderilir. Bu yöntem, kullanıcının tam kelimeyi kullanmasa bile doğru chunk'lara ulaşmasını sağlar.

Görsel belgeler için ise görsel doğrudan vektörize edilmek yerine `gpt-4o-mini` ile detaylı Türkçe açıklama metni üretilir ve bu metin WeKnora'ya kaydedilir. Böylece görsel içerik de metin tabanlı hibrit aramaya dahil edilir; ayrı bir vision embedding pipeline gerektirmez.

**Duplicate tespiti** SHA256 hash'in ilk 16 karakterinin belge başlığına gömülmesiyle (`[hash:xxxx]`) sağlanır; aynı dosyanın tekrar yüklenmesi `409 Conflict` hatası ile engellenir.

---

## Servis Port Haritası

| Servis          | Port    | Açıklama              |
| --------------- | ------- | --------------------- |
| FastAPI         | `8001`  | Ana API               |
| EMQX Dashboard  | `18083` | Broker yönetim paneli |
| EMQX MQTT       | `1883`  | TCP bağlantısı        |
| EMQX WebSocket  | `8083`  | Tarayıcı bağlantısı   |
| WeKnora UI      | `3080`  | KB yönetim arayüzü    |
| WeKnora API     | `8080`  | RAG API (iç ağ)       |
| PostgreSQL (AI) | `5433`  | Uygulama veritabanı   |
| Qdrant          | `6333`  | Vektör DB REST API    |

---

## Proje Yapısı

```
.
├── app/
│   ├── main.py                  # FastAPI uygulama giriş noktası
│   ├── core/
│   │   ├── config.py            # Ortam değişkenleri (Pydantic Settings)
│   │   └── security.py          # JWT, bcrypt, OAuth2
│   ├── db/
│   │   ├── postgres.py          # SQLAlchemy engine & session
│   │   └── deps.py              # DB dependency injection
│   ├── models/                  # SQLAlchemy ORM modelleri
│   │   ├── user.py
│   │   ├── conversation.py
│   │   └── message.py
│   ├── schemas/                 # Pydantic I/O şemaları
│   │   ├── user.py
│   │   ├── conversation.py
│   │   ├── message.py
│   │   └── chat.py
│   ├── routers/                 # FastAPI endpoint'leri
│   │   ├── auth.py
│   │   ├── user.py
│   │   ├── conversation.py
│   │   ├── messages.py
│   │   ├── documents.py
│   │   ├── models.py
│   │   ├── health.py
│   │   └── chat.py              # Ana chat + streaming router
│   └── services/                # İş mantığı katmanı
│       ├── mqtt.py              # EMQX publish helpers
│       ├── rag.py               # WeKnora arama + query expansion
│       ├── vision.py            # OpenRouter vision çağrıları
│       └── weknora_ingestion.py # Belge & görsel yükleme pipeline
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # Ana React bileşeni
│   │   ├── main.jsx
│   │   ├── api.js               # REST API istemcisi
│   │   ├── mqtt.js              # MQTT WebSocket istemcisi
│   │   └── styles.css
│   └── package.json
├── Dockerfile                   # FastAPI container tanımı
├── docker-compose.yml           # Tüm ekosistem orchestration
├── requirements.txt
└── README.md
```
