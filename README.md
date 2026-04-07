<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.111+-009688?logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Android-Jetpack_Compose-3DDC84?logo=android&logoColor=white" />
  <img src="https://img.shields.io/badge/ML-scikit--learn-F7931E?logo=scikit-learn&logoColor=white" />
</p>

# 🛡️ ReviewTrust AI

**AI-powered fake review detection for Amazon & Flipkart products.**

Paste any product URL and get an instant trust score backed by machine learning, sentiment analysis, review spike detection, and AI-generated summaries.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🤖 **ML Classification** | Logistic Regression model trained on labeled fake/genuine reviews, with TF-IDF vectorization |
| 📊 **Trust Score** | Weighted composite score (0-100) combining ML predictions, sentiment curves, and reviewer quality |
| 📈 **Spike Detection** | Flags suspicious bursts of reviews within short time windows |
| 💬 **Sentiment Analysis** | VADER-based polarity analysis with distribution curves |
| 👤 **Reviewer Quality** | Profile-level analysis including review count, verified purchase ratio |
| 📝 **AI Summary** | LSA-powered extractive summary of genuine reviews |
| 🔍 **Explainable AI** | LIME-based per-review explanations showing which words influenced the prediction |
| 🌐 **Multi-Platform** | Supports Amazon (.in/.com) and Flipkart — including short links |

---

## 🏗️ Architecture

```
┌─────────────────────┐         ┌─────────────────────────────────┐
│   Android App       │  HTTP   │   FastAPI Backend               │
│   (Jetpack Compose) │ ──────► │                                 │
│                     │         │  ┌─────────┐  ┌──────────────┐  │
│  • URL Input        │         │  │ Scraper │  │ ML Model     │  │
│  • Trust Dashboard  │         │  │ (PW/CF) │  │ (sklearn)    │  │
│  • Review Cards     │         │  └────┬────┘  └──────┬───────┘  │
│  • Spike Charts     │         │       │              │          │
│  • Explanations     │         │  ┌────▼──────────────▼───────┐  │
│                     │         │  │  Analysis Pipeline        │  │
│                     │  ◄────  │  │  sentiment · spikes ·     │  │
│                     │  JSON   │  │  quality · summary · LIME │  │
└─────────────────────┘         │  └───────────────────────────┘  │
                                └─────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **Android Studio** (for the mobile app)
- **Git**

### 1. Clone & Setup Backend

```bash
git clone https://github.com/<your-username>/ReviewTrust.git
cd ReviewTrust

# Create virtual environment
python -m venv .venv

# Activate it
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Install Playwright's Chromium browser
python -m playwright install chromium

# Download NLTK data (required for summarizer)
python -c "import nltk; nltk.download('punkt_tab')"
```

### 2. Train the ML Model

```bash
cd backend

# Place your training dataset at backend/dataset/fake reviews dataset.csv
# Then run:
python train_model.py
```

This generates `models/fake_review_model.pkl` and `models/vectorizer.pkl`.

### 3. Run the Backend

```bash
cd backend
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000`.

**First run with Amazon URLs:** A Chromium browser window will open — sign into your Amazon account and close the window. The session is saved for all future runs.

### 4. Run the Android App

1. Open the project root in **Android Studio**
2. Update the backend URL in `app/src/main/java/com/reviewtrust/network/RetrofitClient.kt` to point to your backend (e.g. `http://10.0.2.2:8000` for emulator, or your server IP)
3. Build and run on your device/emulator

---

## 📡 API Reference

### `POST /analyze`

Analyze reviews for a product.

**Request Body:**
```json
{
  "url": "https://www.amazon.in/dp/B0G47YZJH6",
  "mode": "normal"
}
```

| Field | Type | Description |
|---|---|---|
| `url` | string | Product URL (Amazon/Flipkart, full or short link) |
| `mode` | string | `"normal"` or `"deep"` (deep includes LIME explanations) |

**Response:** (200 OK)
```json
{
  "trust_score": 85,
  "fake_percentage": 15,
  "genuine_percentage": 85,
  "total_reviews": 21,
  "fake_count": 3,
  "genuine_count": 18,
  "recommendation": "Reviews appear mostly trustworthy.",
  "analysis_mode": "normal",
  "sentiment_analysis": { ... },
  "reviewer_quality": { ... },
  "spike_detection": { ... },
  "review_summary": { ... },
  "fake_reviews": [ ... ],
  "genuine_reviews": [ ... ]
}
```

### `GET /health`

Health check endpoint.

---

## 🖥️ Hosting the Backend

### Option A: Local Network (Easiest)

Run on your PC and point the Android app to your local IP:

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Find your IP with `ipconfig` (Windows) or `ifconfig` (Mac/Linux), then set the Android app's `BASE_URL` to `http://<your-ip>:8000`.

> ⚠️ **Note:** Amazon scraping requires a signed-in Playwright session. The first request to an Amazon URL will open a browser window on your PC for login.

### Option B: VPS / Cloud VM (Recommended for Production)

Deploy on any Linux VPS (e.g. DigitalOcean, AWS EC2, Hetzner):

```bash
# On the server:
sudo apt update && sudo apt install -y python3.11 python3.11-venv

git clone <your-repo-url>
cd ReviewTrust

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m playwright install chromium
python -m playwright install-deps

# Train or upload the model
cd backend
python train_model.py

# Run with a process manager
pip install gunicorn
gunicorn app:app -w 1 -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 --timeout 120
```

> **Important:** Use `-w 1` (single worker) because the ML model and Playwright share process-level state.

For HTTPS, put **nginx** or **Caddy** in front as a reverse proxy.

### Option C: Railway / Render (One-Click Deploy)

1. Push to GitHub
2. Connect the repo to [Railway](https://railway.app) or [Render](https://render.com)
3. Set the build command: `pip install -r backend/requirements.txt && python -m playwright install chromium && python -m playwright install-deps`
4. Set the start command: `cd backend && uvicorn app:app --host 0.0.0.0 --port $PORT`

> ⚠️ **Amazon scraping caveat:** Since Railway/Render are headless-only environments, the interactive Amazon login flow won't work. You'll need to copy your local `playwright_profiles/amazon/` directory to the server, or use Option B with a VPS where you can run a headed browser for initial setup.

---

## 📁 Project Structure

```
ReviewTrust/
├── app/                          # Android app (Jetpack Compose)
│   └── src/main/java/com/reviewtrust/
│       ├── models/               # Data classes (AnalysisResult, etc.)
│       ├── network/              # Retrofit API client
│       └── ui/                   # UI screens (HomeScreen, etc.)
├── backend/                      # Python FastAPI backend
│   ├── app.py                    # FastAPI application & routes
│   ├── scraper.py                # Multi-platform review scraper
│   ├── model.py                  # ML model loader
│   ├── train_model.py            # Model training script
│   ├── sentiment.py              # VADER sentiment analysis
│   ├── spike_detector.py         # Review spike detection
│   ├── reviewer_quality.py       # Reviewer profile analysis
│   ├── summarizer.py             # LSA extractive summarizer
│   ├── trust_score.py            # Composite trust score calculator
│   ├── explain.py                # LIME explainability
│   ├── requirements.txt          # Python dependencies
│   └── models/                   # Trained model files (.pkl)
├── .gitignore
├── build.gradle.kts
├── settings.gradle.kts
└── README.md
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Android** | Kotlin, Jetpack Compose, Retrofit, OkHttp |
| **Backend** | Python, FastAPI, Uvicorn |
| **ML** | scikit-learn (Logistic Regression + TF-IDF) |
| **NLP** | VADER Sentiment, NLTK, Sumy (LSA) |
| **Scraping** | Playwright (Amazon), curl-cffi (Flipkart), BeautifulSoup |
| **Explainability** | LIME |

---

## 📜 License

This project is for educational and research purposes.

---

<p align="center">
  Built with ❤️ for trustworthy online shopping
</p>
