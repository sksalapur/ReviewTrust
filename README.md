<p align="center">
  <img src="app/ic_launcher-playstore.png" alt="ReviewTrust Logo" width="120" />
</p>

<h1 align="center">🛡️ ReviewTrust AI</h1>

<p align="center">
  <strong>Don't trust reviews. Verify them.</strong>
</p>

<p align="center">
  <em>The only consumer tool that runs 6 independent AI/ML analyses on product reviews<br/>and tells you <strong>exactly</strong> which ones are fake — and why.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.111+-009688?logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Android-Jetpack_Compose-3DDC84?logo=android&logoColor=white" />
  <img src="https://img.shields.io/badge/ML-scikit--learn-F7931E?logo=scikit-learn&logoColor=white" />
  <img src="https://img.shields.io/badge/NLP-VADER_%7C_LIME_%7C_LSA-blueviolet" />
  <img src="https://img.shields.io/badge/Platforms-Amazon_%7C_Flipkart_%7C_Nykaa_%7C_Myntra_%7C_Meesho-orange" />
</p>

---

## 🤔 Why Does This Exist?

**60% of online reviews are suspected to be fake or incentivized.** Yet there's no free, consumer-grade tool that actually verifies them at scale. ReviewTrust fills that gap with a 6-stage analysis pipeline that goes far beyond simple sentiment analysis.

| What Others Do | What ReviewTrust Does |
|----------------|----------------------|
| "Positive sentiment detected" | "This review is **fake** because: excessive promotional language, low vocabulary diversity, and pattern resembles computer-generated text" |
| Generic star analysis | Per-review ML classification with LIME explainability |
| No temporal analysis | Detects suspicious review bursts within short time windows |
| No reviewer profiling | Analyzes reviewer history: total review count, verified purchase ratio |
| No summary | LSA-powered extractive summary of genuine reviews |

---

## 🧠 The 6-Stage Analysis Pipeline

```
Product URL (Amazon / Flipkart / Nykaa / Myntra / Meesho)
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  Stage 1: SCRAPING                                       │
│  ├── Amazon: RapidAPI (primary) + Playwright (fallback)  │
│  ├── Flipkart: curl_cffi (Chrome 124 TLS impersonation)  │
│  ├── Nykaa/Myntra: Direct JSON API via curl_cffi          │
│  └── Meesho: Playwright headless (GraphQL)                │
│  Extracts: text, reviewer name, date, verified status     │
├─────────────────────────────────────────────────────────┤
│  Stage 2: ML CLASSIFICATION                               │
│  TF-IDF Vectorization → Logistic Regression               │
│  Output: fake / genuine label per review                  │
├─────────────────────────────────────────────────────────┤
│  Stage 3: SENTIMENT ANALYSIS                              │
│  VADER polarity scoring on genuine reviews only            │
│  Output: positive%, negative%, neutral%, avg compound     │
├─────────────────────────────────────────────────────────┤
│  Stage 4: REVIEW SPIKE DETECTION                          │
│  Temporal analysis of review dates                         │
│  Flags suspicious bursts within short time windows         │
├─────────────────────────────────────────────────────────┤
│  Stage 5: REVIEWER QUALITY PROFILING                      │
│  Per-reviewer analysis: total reviews, verified ratio      │
│  Flags accounts with characteristics of purchased reviews  │
├─────────────────────────────────────────────────────────┤
│  Stage 6: EXPLAINABILITY (LIME)                           │
│  Per-review explanations: which words drove the decision   │
│  Parallel ThreadPoolExecutor for performance              │
│  Human-readable reasons: "Excessive promotional language"  │
├─────────────────────────────────────────────────────────┤
│  BONUS: LSA SUMMARIZATION                                  │
│  Extractive summary of genuine reviews using Sumy LSA      │
│  Gives users a quick "what real buyers think" overview     │
└─────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│  COMPOSITE TRUST SCORE (0–100)              │
│  Fuses: ML predictions + sentiment curves   │
│  + reviewer quality + temporal analysis      │
│                                             │
│  Score ≥ 80: "Safe to buy"                  │
│  Score 60–79: "Proceed with caution"        │
│  Score < 60: "Consider skipping"            │
└─────────────────────────────────────────────┘
```

---

## 🏗️ Architecture

```
┌─────────────────────────┐           ┌──────────────────────────────────┐
│   Android App            │   HTTP    │   FastAPI Backend (Render)       │
│   (Jetpack Compose)      │ ────────► │                                  │
│                          │           │  ┌──────────┐  ┌─────────────┐  │
│  • Paste product URL     │           │  │ Scraper  │  │ ML Model    │  │
│  • View Trust Score      │           │  │ (5 sites)│  │ (TF-IDF +   │  │
│  • Read Explanations     │           │  │          │  │  LogReg)    │  │
│  • Sentiment Charts      │           │  └────┬─────┘  └──────┬──────┘  │
│  • Spike Detection       │           │       │               │         │
│  • AI Summary            │           │  ┌────▼───────────────▼──────┐  │
│                          │   ◄────   │  │   6-Stage Pipeline        │  │
│                          │   JSON    │  │   Sentiment · Spikes ·    │  │
│                          │           │  │   Quality · Summary ·     │  │
│                          │           │  │   LIME Explainability     │  │
└─────────────────────────┘           │  └────────────────────────────┘  │
                                       │                                  │
                                       │  Cache: File-based, 1-week TTL  │
                                       │  Deploy: Docker on Render        │
                                       └──────────────────────────────────┘
```

---

## ✨ Key Features

### 🎯 Per-Review Verdicts with Explanations
Not just "85% trust score" — ReviewTrust classifies **every single review** and tells you *why*:
- "Excessive promotional language detected"
- "Low vocabulary diversity"
- "Pattern resembles computer-generated text"
- "Balanced sentiment with pros and cons"
- "Critical feedback with specifics"

### 📊 Intelligent Caching
- SHA-256 URL canonicalization (strips tracking params, resolves short links)
- File-based cache with 1-week TTL — instant results for repeated queries
- Separate analysis modes: **Normal** (fast, 60 reviews, 5 LIME explanations) vs **Deep** (unlimited, 20 LIME explanations)

### 🕷️ Multi-Platform Scraping Engine (5 E-Commerce Sites)
| Platform | Strategy | Anti-Bot Bypass |
|----------|----------|-----------------|
| **Amazon** | RapidAPI (primary) + Playwright (fallback) | Real-time API / persistent signed-in browser profile |
| **Flipkart** | curl_cffi | Chrome 124 TLS fingerprint impersonation |
| **Nykaa** | Direct JSON API | curl_cffi with browser headers |
| **Myntra** | xt.myntra.com JSON API | curl_cffi with browser headers |
| **Meesho** | Playwright headless | Full browser rendering for GraphQL |

### 📈 Temporal Spike Detection
Detects suspicious patterns like 50 five-star reviews posted within 3 days — a telltale sign of paid review campaigns.

### 👤 Reviewer Quality Profiling
Analyzes reviewer accounts: total review count, verified purchase ratio, and writing patterns to flag professionally-operated fake review accounts.

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Android** | Kotlin, Jetpack Compose, Material 3 | Native UI with rich dashboard |
| **Network** | Retrofit + OkHttp | Type-safe backend communication |
| **Backend** | Python, FastAPI, Uvicorn | Async API serving the ML pipeline |
| **ML** | scikit-learn (Logistic Regression + TF-IDF) | Binary classification: fake vs genuine |
| **NLP** | VADER Sentiment, NLTK | Polarity scoring and text processing |
| **Explainability** | LIME (Local Interpretable Model-agnostic Explanations) | Per-review feature attribution |
| **Summarization** | Sumy LSA (Latent Semantic Analysis) | Extractive summary of genuine reviews |
| **Scraping** | curl_cffi, Playwright, BeautifulSoup, RapidAPI | Multi-strategy review extraction |
| **Deployment** | Docker, Render | Production cloud hosting |

---

## 📐 Project Structure

```
ReviewTrust/
├── app/                              # Android App
│   └── src/main/java/com/reviewtrust/
│       ├── models/                   # AnalysisResult data class
│       ├── network/                  # Retrofit client + ApiService
│       ├── repository/              # ReviewRepository
│       ├── charts/                   # MPAndroidChart helpers
│       └── ui/
│           ├── HomeScreen.kt         # Main dashboard with URL input
│           ├── ReviewViewModel.kt    # State management
│           └── Navigation.kt         # Compose navigation
│
├── backend/                          # Python ML Backend
│   ├── app.py                        # FastAPI app + /analyze endpoint
│   ├── scraper.py                    # 1,586 lines — 5-platform scraper
│   ├── model.py                      # Trained model loader
│   ├── train_model.py                # Model training script
│   ├── sentiment.py                  # VADER sentiment analysis
│   ├── spike_detector.py             # Temporal review burst detection
│   ├── reviewer_quality.py           # Reviewer profile analysis
│   ├── summarizer.py                 # Sumy LSA extractive summarizer
│   ├── trust_score.py                # Composite trust score calculator
│   ├── explain.py                    # LIME explainability engine
│   ├── models/
│   │   ├── fake_review_model.pkl     # Trained LogReg model
│   │   └── vectorizer.pkl            # Trained TF-IDF vectorizer
│   └── dataset/
│       └── reviews.csv              # Training dataset
│
├── Dockerfile                        # Production container
├── render.yaml                       # Render deployment config
└── streamlit_app.py                  # Alternative web UI
```

---

## 🚀 Quick Start

### Backend
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python train_model.py              # Generate model .pkl files
uvicorn app:app --port 8000 --reload
```

### Android App
1. Open project in Android Studio
2. Update `BASE_URL` in `RetrofitClient.kt` to your backend URL
3. Build and run

---

<p align="center">
  <strong>Fake reviews cost consumers billions every year.</strong><br/>
  <em>This is the tool that fights back.</em>
</p>

<p align="center">
  Made with ❤️ by <a href="https://github.com/sksalapur">Sharanbasav Salapur</a>
</p>
