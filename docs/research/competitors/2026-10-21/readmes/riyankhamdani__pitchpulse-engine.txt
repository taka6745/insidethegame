# ⚽ PitchPulse Engine
> Real-Time Multi-Agent Synthetic Match Intelligence & Broadcast Engine for Premier League Studio

PitchPulse transforms high-frequency synthetic match event streams into explainable tactical intelligence, machine-readable broadcast overlays, and personalized narratives for pundits and global fans.

---

## 📌 Architecture Overview

PitchPulse decouples high-speed deterministic calculation from cognitive LLM tactical reasoning to ensure low-latency broadcast rendering and resilience against API rate-limits.

```text
       [ Synthetic Event Stream ] (Coordinates, Action, Pressure)
                   │
                   ▼
       ┌────────────────────────┐
       │  FeatureWorkerAgent    │ ➔ Stage 1 & 2: Ingest & Interpret
       │ (Deterministic Metrics)│   (Pass Difficulty, Field Vector)
       └───────────┬────────────┘
                   │ Enriched Event Payload
                   ▼
       ┌────────────────────────┐
       │ TacticalReasonerAgent  │ ➔ Stage 3: Explainable Reasoning
       │   (State Evaluation)   │   (Chaos vs Control, Phase Shifts)
       └───────────┬────────────┘
                   │ Structured Tactical State
                   ▼
       ┌────────────────────────┐
       │ PersonaDispatcherAgent │ ➔ Stage 4 & 5: Render & Personalize
       │ (Multi-Language Studio)│   (Analyst HUD vs Casual Fan Narratives)
       └───────────┬────────────┘
                   │
       ┌───────────┴────────────┐
       ▼                        ▼
[ Broadcast Lower-Third ]   [ 2D Tactical Radar ]
```

---

## 🚀 5-Stage Pipeline Implementation

1. **(a) Real-Time Ingestion:** Ingests simulated match events (passes, tackles, interceptions, shots) and field coordinates without relying on restricted third-party data feeds.
2. **(b) High-Speed Interpretation:** `FeatureWorkerAgent` deterministically calculates progression distance, pass difficulty score, and pressing intensity in sub-second cycles.
3. **(c) Explainable Tactical Reasoning:** `TacticalReasonerAgent` determines the momentum state (`Controlled Progression`, `Stable Circulation`, or `High Chaos / Vulnerability`) to answer *why* the tactical moment matters.
4. **(d) Studio-Ready Rendering:** Streams structured outputs straight into broadcast-ready components, including lower-third metric cards and live vector overlays.
5. **(e) Multi-Persona Personalization:** `PersonaDispatcherAgent` dynamically formats insights into deep analytical breakdowns for pundits or punchy commentary in English, Bahasa Indonesia, and Spanish for casual viewers.

---

## 🧠 Multi-Agent Responsibilities

| Agent Name | Core Responsibility | Output / Artifact |
| :--- | :--- | :--- |
| **Feature Worker Agent** | Geometric parsing & progression math | `Diff_Score`, progression distance, risk flags |
| **Tactical Reasoner Agent** | Momentum analysis & defensive collapse detection | `tactical_state`, root-cause rationale |
| **Persona Dispatcher Agent** | Tone modulation & multilingual localization | Tailored broadcast copy & lower-third banners |

---

## 🛠️ Tech Stack

* **Language & Engine:** Python 3.11, Streamlit
* **Pitch Visualization:** `mplsoccer`, `matplotlib`
* **Data Processing:** `pandas`, `numpy`
* **AI Orchestration:** Multi-Agent Cooperative Architecture (Azure OpenAI / GitHub Models compatible)
* **Cloud Dev Environment:** GitHub Codespaces (Zero-Footprint Execution)

---

## ⚡ Quickstart (Local & GitHub Codespaces)

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/riyankhamdani/pitchpulse-engine.git](https://github.com/riyankhamdani/pitchpulse-engine.git)
   cd pitchpulse-engine
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Launch the studio dashboard:**
   ```bash
   python -m streamlit run app.py
   ```