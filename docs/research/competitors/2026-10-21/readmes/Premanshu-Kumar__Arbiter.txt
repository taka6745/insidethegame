# 🤖 Multi-Agent Data Analyst

> **A Jev-powered, local-first AI data analyst that combines fast decision-making with local LLMs to analyze CSV and Excel files.**

Ask questions about your data in plain English. The system automatically profiles the dataset, decides the best analysis strategy, generates SQL or Python using a local LLM, executes it safely, validates the result, creates visualizations, and generates a complete analytical report.

### **Jev decides. LLMs generate. LangGraph orchestrates.**

---

## ✨ Highlights

* 🧠 **Jev-powered decision engine**
* 🤖 **Local LLMs through Ollama**
* 📊 **CSV & Excel analysis**
* 🐍 **Python/Pandas analysis**
* 🗄️ **DuckDB SQL analytics**
* 🔄 **Self-healing agent workflow**
* 🛡️ **Sandboxed code execution**
* 📈 **Automatic Plotly visualizations**
* 📝 **AI-generated reports**
* 🔍 **Validation and confidence checks**
* 🕸️ **LangGraph multi-agent orchestration**
* 🖥️ **Interactive Streamlit interface**
* 🔐 **Local-first data processing**

---

# 🧠 Why Jev + LLM?

Instead of asking one LLM to perform every task, this project separates **decision-making** from **generation**.

```text
                 ┌─────────────────┐
                 │      Jev        │
                 │ Decision Engine │
                 └────────┬────────┘
                          │
          ┌───────────────┼───────────────┐
          ↓               ↓               ↓
       Routing        Validation        Retry
          │               │               │
          └───────────────┼───────────────┘
                          ↓
                 ┌─────────────────┐
                 │   Local LLM     │
                 │     Ollama      │
                 └────────┬────────┘
                          │
                 ┌────────┼────────┐
                 ↓        ↓        ↓
                SQL     Python   Reports
```

### Jev handles

* SQL vs Python vs BOTH decisions
* Agent selection
* Validation decisions
* Retry decisions
* Visualization selection
* Confidence-based routing
* Workflow branching

### LLMs handle

* SQL generation
* Python generation
* Code correction
* Data interpretation
* Insight generation
* Natural-language explanations
* Report generation

This prevents the generative LLM from being unnecessarily used for simple bounded decisions.

---

# 🏗️ Architecture

```text
                         User
                          │
                          ▼
                 ┌─────────────────┐
                 │   Streamlit UI  │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │  Data Profiler  │
                 │ Pandas / DuckDB │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │      Jev        │
                 │ Planner/Router  │
                 └────────┬────────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
              ▼           ▼           ▼
           SQL Agent   Python Agent   BOTH
              │           │           │
              └───────────┼───────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │  Local LLM      │
                 │ Ollama + Coder  │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │  Safe Executor  │
                 │ Python + DuckDB │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │      Jev        │
                 │    Validator    │
                 └────────┬────────┘
                          │
                    ┌─────┴─────┐
                    │           │
                   PASS        FAIL
                    │           │
                    ▼           ▼
             Visualization    Retry
                    │           │
                    │           └──────► Agent
                    ▼
             ┌───────────────┐
             │ Report Agent  │
             └───────┬───────┘
                     │
                     ▼
                HTML / PDF
```

---

# 🔄 How It Works

## 1. Upload Data

Supported formats:

```text
.csv
.xlsx
.xls
```

The system automatically profiles the dataset.

Example:

```text
Rows: 125,430

Columns:
- order_date
- customer_id
- category
- product
- quantity
- revenue

Missing Values:
- customer_id: 2.1%
- category: 0%
- revenue: 0%
```

---

## 2. Ask a Question

Example:

> **Which product category generated the highest revenue in 2024 and how did it trend month by month?**

---

## 3. Jev Plans the Analysis

Jev converts the question into a structured decision.

Example:

```json
{
  "method": "SQL",
  "requires_time_series": true,
  "group_by": ["category", "month"],
  "visualization": "line_chart",
  "validation": true
}
```

---

## 4. LLM Generates Code

The local coding model receives the structured plan and dataset schema.

Example:

```sql
SELECT
    category,
    DATE_TRUNC('month', order_date) AS month,
    SUM(revenue) AS revenue
FROM sales
WHERE EXTRACT(YEAR FROM order_date) = 2024
GROUP BY category, month
ORDER BY month;
```

---

## 5. Safe Execution

Generated code is checked before execution.

```text
Generated Code
      ↓
Safety Validation
      ↓
Sandbox
      ↓
Timeout
      ↓
Execution
      ↓
Result
```

---

## 6. Jev Validates the Result

Jev evaluates whether the execution should continue.

Possible decisions:

```text
ACCEPT
RETRY
SWITCH_METHOD
REJECT
```

---

## 7. Self-Healing

If the generated code fails:

```text
LLM
 ↓
Generated Code
 ↓
Execution
 ↓
ERROR
 ↓
Jev
 ↓
RETRY
 ↓
LLM
 ↓
Corrected Code
```

Retries are limited to prevent infinite loops.

---

## 8. Visualization

The system automatically selects an appropriate chart.

Supported visualizations include:

* Line charts
* Bar charts
* Scatter plots
* Histograms
* Box plots
* Time-series charts
* Category comparisons

Charts are generated using **Plotly**.

---

## 9. Report Generation

The report agent produces:

* Executive summary
* Key insights
* Data tables
* Visualizations
* Analysis methodology
* Validation status

Export formats:

```text
Markdown
HTML
PDF
```

---

# 🧠 Multi-Agent System

| Component           | Responsibility      | Technology      |
| ------------------- | ------------------- | --------------- |
| Data Profiler       | Schema & statistics | Pandas          |
| Planner             | Analysis strategy   | **Jev**         |
| SQL Agent           | SQL generation      | Local LLM       |
| Python Agent        | Python generation   | Local LLM       |
| Executor            | Safe execution      | Python / DuckDB |
| Validator           | Result validation   | **Jev + LLM**   |
| Visualization Agent | Chart generation    | Plotly          |
| Report Agent        | Report generation   | Local LLM       |
| Orchestrator        | Workflow management | LangGraph       |
| UI                  | User interface      | Streamlit       |

---

# 🧩 Shared LangGraph State

```python
class AnalystState(TypedDict):
    question: str
    schema: str

    # Jev decisions
    decision: dict
    confidence: float

    # Agent execution
    selected_agent: str
    code: str
    code_type: str

    # Results
    result: Any
    error: str | None

    # Validation
    valid: bool
    validation_reason: str

    # Retry
    retry_count: int
    failed_agent: str | None

    # Output
    charts: list[str]
    insights: list[str]
    report: str
```

---

# 🧠 Model Strategy

The project uses different models for different tasks.

### Decision Layer

**Jev**

Used for:

```text
Routing
Classification
Agent selection
Validation
Retry decisions
Workflow branching
```

### Generation Layer

Local models through Ollama.

Recommended starting models:

```text
Qwen3-Coder
Qwen3
```

Example configuration:

```python
CODER_MODEL = "qwen3-coder"
REASONING_MODEL = "qwen3"
```

Models can be changed through the project configuration without changing the architecture.

---

# 🛠️ Tech Stack

| Category        | Technology                |
| --------------- | ------------------------- |
| Decision Engine | **Jev**                   |
| LLM Runtime     | **Ollama**                |
| Coding LLM      | **Qwen3-Coder**           |
| Reasoning LLM   | **Qwen3**                 |
| Orchestration   | **LangGraph**             |
| Data Processing | **Pandas**                |
| SQL Analytics   | **DuckDB**                |
| Excel           | **OpenPyXL**              |
| Visualization   | **Plotly**                |
| UI              | **Streamlit**             |
| Templates       | **Jinja2**                |
| Reports         | **Markdown / WeasyPrint** |
| Testing         | **Pytest**                |

---

# 📁 Project Structure

```text
multi-agent-analyst/
│
├── app.py
├── graph.py
├── state.py
├── config.py
│
├── agents/
│   ├── profiler.py
│   ├── jev_planner.py
│   ├── sql_agent.py
│   ├── python_agent.py
│   ├── viz_agent.py
│   ├── jev_validator.py
│   └── report_agent.py
│
├── decision/
│   ├── jev_client.py
│   ├── schemas.py
│   └── policies.py
│
├── sandbox/
│   ├── executor.py
│   └── safety.py
│
├── prompts/
│   ├── sql.txt
│   ├── python.txt
│   └── report.txt
│
├── templates/
│   └── report.html
│
├── eval/
│   ├── questions.json
│   └── run_eval.py
│
├── data/
│   └── sample.csv
│
├── reports/
│
├── tests/
│
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

# 🚀 Installation

## Prerequisites

* Python 3.10+
* Ollama
* Jev access/configuration
* Git
* 16 GB RAM recommended for larger local models

---

## 1. Clone

```bash
git clone https://github.com/<your-username>/multi-agent-analyst.git

cd multi-agent-analyst
```

---

## 2. Create Virtual Environment

### Windows

```bash
python -m venv venv
venv\Scripts\activate
```

### Linux / macOS

```bash
python -m venv venv
source venv/bin/activate
```

---

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 4. Install Local Models

Start Ollama and pull the models configured for the project.

Example:

```bash
ollama pull qwen3-coder
ollama pull qwen3
```

---

## 5. Configure Environment

Create a `.env` file:

```env
JEV_API_KEY=your_jev_key
JEV_MODEL=your_jev_model

OLLAMA_BASE_URL=http://localhost:11434

CODER_MODEL=qwen3-coder
REASONING_MODEL=qwen3
```

### Never commit `.env`

Make sure:

```text
.env
```

is included in `.gitignore`.

---

## 6. Run

```bash
streamlit run app.py
```

Then upload your dataset and start asking questions.

---

# 🔐 Security

Generated code is treated as **untrusted input**.

## Python Protection

The execution layer can enforce:

* AST validation
* Restricted imports
* Subprocess execution
* Execution timeouts
* Restricted filesystem access
* Network restrictions

Potentially dangerous operations such as:

```text
os
subprocess
socket
requests
eval
exec
```

should be blocked according to the configured sandbox policy.

For stronger isolation, Docker-based execution is recommended.

---

## SQL Protection

The SQL agent is restricted to analytical queries.

Allowed:

```sql
SELECT ...
```

Blocked:

```text
DROP
DELETE
UPDATE
INSERT
ALTER
CREATE
ATTACH
```

DuckDB is used for local analytical workloads.

---

# 🔄 Error Handling

The system supports automatic recovery from generated-code failures.

```text
           Generate
               ↓
            Execute
               ↓
             Error?
           /       \
         NO         YES
         ↓           ↓
     Validate       Jev
                     ↓
               Retry decision
                     ↓
                  LLM Agent
                     ↓
                Correct code
                     ↓
                  Execute
```

Maximum retries:

```python
MAX_RETRIES = 3
```

If all retries fail, the system returns an explanation instead of looping indefinitely.

---

# 🧪 Evaluation

The project includes an evaluation framework for measuring agent performance.

Metrics include:

* Execution success rate
* Answer accuracy
* Jev routing accuracy
* Validation accuracy
* Average retries
* Average latency
* LLM calls per question
* Failed executions

Example:

```bash
python eval/run_eval.py
```

---

# 📊 Jev vs LLM Benchmark

One of the project's experimental goals is to measure the difference between specialized decision-making and generative decision-making.

```text
                  Decision Task
                       │
              ┌────────┴────────┐
              ↓                 ↓
             Jev               LLM
              │                 │
              └────────┬────────┘
                       ↓
                  Evaluation
                       │
          ┌────────────┼────────────┐
          ↓            ↓            ↓
       Accuracy      Latency       Cost
```

This can help determine where a specialized decision model provides an advantage over using an LLM for every workflow decision.

---

# 🗺️ Roadmap

## Phase 1 — Foundation

* [x] Project architecture
* [ ] CSV/Excel upload
* [ ] Data profiler
* [ ] Ollama integration
* [ ] Jev integration

## Phase 2 — Agents

* [ ] Jev Planner
* [ ] SQL Agent
* [ ] Python Agent
* [ ] Visualization Agent
* [ ] Report Agent

## Phase 3 — Execution

* [ ] DuckDB execution
* [ ] Python sandbox
* [ ] AST safety checks
* [ ] Timeout handling
* [ ] SQL allow-list

## Phase 4 — LangGraph

* [ ] Shared state
* [ ] Conditional edges
* [ ] Jev decision nodes
* [ ] Agent nodes
* [ ] Retry cycles

## Phase 5 — Validation

* [x] Jev validator
* [x] Result validation
* [x] Empty-result detection
* [x] NaN detection
* [x] SQL/Pandas cross-check
* [x] Self-healing retries

## Phase 6 — UI

* [ ] Streamlit dashboard
* [ ] Agent trace
* [ ] SQL/Python viewer
* [ ] Interactive charts
* [ ] Report export

## Phase 7 — Advanced

* [ ] Multi-file joins
* [ ] Automatic EDA
* [ ] Docker sandbox
* [ ] Dataset versioning
* [ ] Jev vs LLM benchmarking
* [ ] Model performance dashboard

## Phase 8 — Excel & Google Sheets Integration

### Goal

Extend the Multi-Agent Data Analyst from file-upload based analysis to direct spreadsheet workflows, allowing users to analyze, transform, visualize, and export spreadsheet data.

### Excel Support

Phase 8 will expand the existing Excel support with:

* [ ] Multi-sheet Excel workbooks
* [ ] Sheet selection
* [ ] Multi-sheet analysis
* [ ] Excel result export
* [ ] Summary and insights sheets
* [ ] Chart/result export

Supported formats:

```text
.xlsx
.xls
.csv
```

Example workbook:

```text
sales.xlsx
│
├── Sales
├── Customers
├── Products
└── Regions
```

### Google Sheets Integration

Add the ability to connect a Google Spreadsheet and use it as a data source.

```text
Google Account
      ↓
Google Sheets
      ↓
Select Spreadsheet
      ↓
Select Sheet
      ↓
Data Profiler
      ↓
Jev
      ↓
LangGraph
      ↓
Agents
      ↓
Analysis
```

Planned capabilities:

* [ ] Google OAuth authentication
* [ ] Spreadsheet selection
* [ ] Sheet selection
* [ ] Read spreadsheet data
* [ ] Analyze spreadsheet data
* [ ] Create an analysis sheet
* [ ] Write results back to Google Sheets

### Excel Add-in

As an advanced extension, provide an AI analyst directly inside Microsoft Excel.

```text
Microsoft Excel
      ↓
Excel Add-in
      ↓
AI Analyst
      ↓
Jev
      ↓
LangGraph
      ↓
SQL / Python / Visualization Agents
      ↓
Results
      ↓
Excel
```

Planned technologies:

```text
Office.js
TypeScript
React
Microsoft Excel JavaScript API
```

### Spreadsheet Workflow

```text
Excel / Google Sheets
          ↓
      Data Import
          ↓
     Data Profiling
          ↓
          Jev
          ↓
      LangGraph
          ↓
   ┌──────┴──────┐
   ↓             ↓
 SQL Agent   Python Agent
   ↓             ↓
 DuckDB        Pandas
   └──────┬──────┘
          ↓
   Visualization
          ↓
      Validation
          ↓
       Insights
          ↓
        Report
          ↓
 Excel / Google Sheets
```

### Example Questions

Users should be able to ask questions such as:

> Which region generated the highest profit?

> Show the monthly revenue trend.

> Find the top 20 customers by sales.

> Identify missing and duplicate records.

> Create a chart showing sales by region.

> Analyze why revenue decreased in the last quarter.

### Phase 8 Success Criteria

Phase 8 will be considered complete when a user can:

1. Upload an Excel workbook or connect Google Sheets.
2. Select one or more sheets.
3. Ask a natural-language question.
4. Let Jev select the analysis strategy.
5. Execute the analysis through the existing agent workflow.
6. View tables, charts, and insights.
7. Export or write results back to the spreadsheet.

This phase keeps the existing **Jev + Local LLM + LangGraph** architecture while extending the project into practical spreadsheet workflows.

---

## Phase 8 — Spreadsheet Integration

* [ ] Multi-sheet Excel support
* [ ] Excel sheet selection
* [ ] Multi-sheet analysis
* [ ] Excel result export
* [ ] Summary and insights sheets
* [ ] Chart/result export
* [ ] Google Sheets integration
* [ ] Google OAuth authentication
* [ ] Google Sheets data retrieval
* [ ] Google Sheets result write-back
* [ ] Excel Add-in
* [ ] Office.js integration
* [ ] Spreadsheet analysis workflow
* [ ] Natural-language spreadsheet queries
* [ ] Spreadsheet visualization and reporting

# Phase 9 — Advanced Analytics & Machine Learning

### Goal

Extend the Multi-Agent Data Analyst from descriptive and diagnostic analysis into **predictive and advanced analytical workflows**.

Phase 9 allows the system to automatically identify when a question requires machine learning, statistical analysis, forecasting, anomaly detection, or other advanced analytical methods.

The existing architecture remains unchanged:

```text
User
 ↓
Data Profiler
 ↓
Jev
 ↓
LangGraph
 ↓
ML / Analytics Agent
 ↓
Local LLM
 ↓
Sandbox
 ↓
Validator
 ↓
Insights + Visualization
```

---

## 🧠 Advanced Analytics Agent

Introduce an analytics/ML agent responsible for selecting and executing advanced analytical methods.

Possible tasks:

* [ ] Predictive analytics
* [ ] Time-series forecasting
* [ ] Anomaly detection
* [ ] Regression
* [ ] Classification
* [ ] Clustering
* [ ] Correlation analysis
* [ ] Feature engineering
* [ ] Statistical analysis
* [ ] Automated model selection

---

## 📈 Predictive Analytics

The system should understand questions such as:

> Predict next month's revenue.

> Forecast sales for the next 6 months.

> Which customers are likely to churn?

Example workflow:

```text
Dataset
   ↓
Jev
   ↓
Identify Prediction Task
   ↓
ML Agent
   ↓
Feature Engineering
   ↓
Model Selection
   ↓
Model Training
   ↓
Validation
   ↓
Prediction
   ↓
Visualization
   ↓
Report
```

---

## 📊 Forecasting

Support time-series forecasting for suitable datasets.

Example:

```text
Historical Data
      ↓
Time-Series Detection
      ↓
Feature Preparation
      ↓
Forecasting Model
      ↓
Future Predictions
      ↓
Chart + Insights
```

Possible outputs:

* Historical trend
* Forecasted values
* Prediction intervals
* Trend analysis
* Forecast visualization

---

## 🚨 Anomaly Detection

The system should identify unusual observations.

Example:

> Find unusual transactions in my sales data.

Workflow:

```text
Dataset
   ↓
Jev
   ↓
Anomaly Detection
   ↓
Feature Selection
   ↓
Model / Statistical Method
   ↓
Anomalies
   ↓
Visualization
   ↓
Explanation
```

Possible methods:

```text
Statistical thresholds
Isolation Forest
Local Outlier Factor
Clustering-based detection
```

---

## 📉 Regression

Support regression tasks such as:

> Predict house price from the available features.

Possible workflow:

```text
Dataset
   ↓
Feature Engineering
   ↓
Train/Test Split
   ↓
Regression Model
   ↓
Validation
   ↓
Prediction
   ↓
Metrics
```

Possible models:

```text
Linear Regression
Random Forest
Gradient Boosting
XGBoost
LightGBM
```

---

## 🏷️ Classification

Support classification questions such as:

> Predict whether a customer is likely to churn.

Possible models:

```text
Logistic Regression
Decision Tree
Random Forest
Gradient Boosting
XGBoost
LightGBM
```

Evaluation metrics:

```text
Accuracy
Precision
Recall
F1 Score
ROC-AUC
Confusion Matrix
```

---

## 🔵 Clustering

Support unsupervised analysis such as:

> Segment customers based on purchasing behavior.

Possible methods:

```text
K-Means
Hierarchical Clustering
DBSCAN
```

Possible outputs:

* Customer segments
* Cluster sizes
* Cluster characteristics
* Visualization
* Segment descriptions

---

## 🧪 Model Validation

Every ML workflow should include validation.

```text
Data
 ↓
Train
 ↓
Validation
 ↓
Evaluation
 ↓
Model Check
 ↓
Prediction
```

The system should report appropriate metrics rather than presenting predictions without context.

---

## 🧠 Jev + ML Routing

Jev should determine whether a question requires:

```text
SQL
Python
SQL + Python
Visualization
Machine Learning
Forecasting
Anomaly Detection
```

Example:

```json
{
  "method": "ML",
  "task": "forecasting",
  "target": "revenue",
  "time_column": "date",
  "validation": true
}
```

---

## 📊 ML Visualization

Automatically generate appropriate visualizations.

Examples:

```text
Forecast → Line Chart
Classification → Confusion Matrix
Regression → Actual vs Predicted
Clustering → Scatter Plot
Anomaly Detection → Highlighted Time Series
```

---

## 📄 ML Report

The Report Agent should include:

* Problem definition
* Dataset information
* Features used
* Method selected
* Model used
* Evaluation metrics
* Predictions
* Visualizations
* Important findings
* Limitations

Example:

```text
Machine Learning Report
────────────────────────

Problem:
Revenue Forecasting

Model:
[Selected Model]

Validation:
[Metrics]

Forecast:
[Chart]

Key Insights:
[Generated Insights]
```

---

## 🔐 ML Safety

ML-generated code must continue to pass through the existing security architecture:

```text
LLM Generated Code
       ↓
AST Validation
       ↓
Safety Policy
       ↓
Sandbox
       ↓
Execution
       ↓
Validator
```

---

## 🧪 Phase 9 Testing

* [ ] Regression tests
* [ ] Classification tests
* [ ] Forecasting tests
* [ ] Clustering tests
* [ ] Anomaly detection tests
* [ ] Feature engineering tests
* [ ] Model validation tests
* [ ] Prediction validation
* [ ] Visualization tests
* [ ] ML report tests

---

## Phase 9 Success Criteria

Phase 9 will be considered complete when the system can:

1. Detect when a question requires advanced analytics.
2. Select an appropriate ML/analytics workflow.
3. Prepare the dataset.
4. Train or execute the selected analytical method.
5. Validate the result.
6. Generate appropriate visualizations.
7. Explain the results in natural language.
8. Include the analysis in the final report.

---

## Phase 9 Roadmap

* [ ] Advanced Analytics Agent
* [ ] Feature Engineering
* [ ] Regression
* [ ] Classification
* [ ] Clustering
* [ ] Anomaly Detection
* [ ] Forecasting
* [ ] Automated Model Selection
* [ ] Model Validation
* [ ] ML Visualization
* [ ] ML Reports
* [ ] ML Evaluation Suite

# Phase 10 — Production, Deployment & SaaS

### Goal

Transform the Multi-Agent Data Analyst from a development project into a **production-ready application** that can be deployed and used by multiple users.

The architecture evolves from:

```text
Local Development
      ↓
Production Application
      ↓
Cloud Deployment
      ↓
Multi-User Platform
```

---

## 🏗️ Production Architecture

```text
                         USERS
                           │
                           ▼
                    Web Application
                           │
                           ▼
                     API Gateway
                           │
                ┌──────────┴──────────┐
                ▼                     ▼
             FastAPI              Authentication
                │
                ▼
             LangGraph
                │
        ┌───────┼────────┐
        ▼       ▼        ▼
      Jev     Agents    ML
                │
        ┌───────┼────────┐
        ▼       ▼        ▼
     DuckDB   Database  Sandbox
                │
                ▼
             Storage
                │
                ▼
           Reports / Files
```

---

## 🌐 Web Application

Move beyond the development Streamlit interface toward a production web application.

Potential frontend:

```text
React
TypeScript
Next.js
```

Backend:

```text
FastAPI
Python
```

Features:

* [ ] User dashboard
* [ ] File upload
* [ ] Data preview
* [ ] Chat interface
* [ ] Analysis history
* [ ] Charts
* [ ] Reports
* [ ] Project management
* [ ] Settings

---

## 🔐 Authentication

Add secure user authentication.

Possible features:

* [ ] User registration
* [ ] Login
* [ ] Logout
* [ ] Password security
* [ ] Session management
* [ ] OAuth
* [ ] Role-based access
* [ ] API authentication

Possible roles:

```text
Admin
User
Team Member
```

---

## 👥 Multi-User Support

Allow multiple users to use the platform independently.

```text
User
 ↓
Workspace
 ↓
Projects
 ↓
Datasets
 ↓
Analyses
 ↓
Reports
```

Each user's data should remain isolated from other users.

---

## 📁 Project Management

Users should be able to create projects.

Example:

```text
My Projects
│
├── Sales Analysis
│   ├── sales.xlsx
│   ├── analyses
│   └── reports
│
├── Customer Analytics
│   ├── customers.csv
│   └── reports
│
└── Revenue Forecast
    ├── revenue.xlsx
    └── models
```

---

## 💾 Database

Introduce a production database for application state.

Potential technology:

```text
PostgreSQL
```

Possible entities:

```text
Users
Projects
Datasets
Analyses
Queries
Reports
Models
API Keys
Audit Events
```

---

## ☁️ File Storage

Large datasets and generated reports should use dedicated storage.

Possible options:

```text
Object Storage
S3-compatible storage
Cloud storage
```

Store:

```text
Uploaded datasets
Generated reports
Charts
ML models
Analysis artifacts
```

---

## 🐳 Production Docker

Containerize the application.

Example:

```text
Docker
│
├── Frontend
├── Backend
├── Worker
├── Database
└── Sandbox
```

Production execution should keep AI-generated code isolated from the main application.

---

## ⚙️ Background Jobs

Long-running analyses should not block the main web server.

Example:

```text
User Request
     ↓
FastAPI
     ↓
Job Queue
     ↓
Worker
     ↓
LangGraph
     ↓
Analysis
     ↓
Result
```

Possible tasks:

* Large dataset analysis
* ML training
* Forecasting
* Report generation
* Scheduled analysis

---

## 📊 Monitoring

Add monitoring for:

```text
API latency
Agent execution time
LLM latency
Jev latency
Model errors
Sandbox failures
Database errors
Failed analyses
```

Track:

```text
Requests
Errors
Retries
Token/model usage
Execution time
Resource usage
```

---

## 📝 Logging

Create structured logs for important events.

Example:

```text
Request Started
      ↓
Dataset Loaded
      ↓
Jev Decision
      ↓
Agent Selected
      ↓
Code Generated
      ↓
Sandbox Executed
      ↓
Validation
      ↓
Report Generated
```

Sensitive data should not be unnecessarily written to logs.

---

## 🔐 Production Security

Security becomes a major requirement.

Implement:

* [ ] Authentication
* [ ] Authorization
* [ ] Input validation
* [ ] Rate limiting
* [ ] Secure file handling
* [ ] Sandbox isolation
* [ ] Network restrictions
* [ ] Secret management
* [ ] API key protection
* [ ] Audit logging
* [ ] Data isolation

Generated code must continue to be treated as untrusted.

```text
Generated Code
      ↓
Safety Validation
      ↓
Restricted Sandbox
      ↓
Resource Limits
      ↓
Execution
```

---

## 🔑 API Management

Provide an API for external applications.

Example:

```text
POST /api/analyze
POST /api/datasets
GET  /api/projects
GET  /api/analyses
GET  /api/reports
```

Possible integrations:

```text
Excel
Google Sheets
Power BI
Custom Applications
Internal Tools
```

---

## 📊 Usage & Quotas

For a multi-user platform, track resource usage.

Possible limits:

```text
Files per project
Maximum file size
Analyses per day
Execution time
ML training resources
Storage
API requests
```

---

## 💳 SaaS Layer

The application can eventually support subscription-based plans.

Example structure:

```text
Free
│
├── Limited analyses
├── Smaller datasets
└── Basic reports

Pro
│
├── Larger datasets
├── Advanced analytics
├── More analyses
└── Advanced reports

Team
│
├── Shared workspaces
├── Team members
├── Collaboration
└── Higher limits
```

The exact pricing and limits should be determined separately when the production business model is defined.

---

## 🔌 Integrations

Production version can expose integrations for:

```text
Excel
Google Sheets
Power BI
Databases
REST APIs
Cloud Storage
```

Example:

```text
External Application
        ↓
     API
        ↓
   Multi-Agent
   Data Analyst
        ↓
     Analysis
        ↓
     Results
```

---

## 📈 Production Analytics

Track platform-level metrics:

```text
Total users
Active users
Total analyses
Successful analyses
Failed analyses
Average analysis time
Average retries
Most-used agents
Most-used models
```

These metrics should be collected without exposing users' private dataset contents.

---

## 🧪 Production Testing

Add:

* [ ] Unit tests
* [ ] Integration tests
* [ ] API tests
* [ ] Authentication tests
* [ ] Security tests
* [ ] Sandbox tests
* [ ] Load tests
* [ ] End-to-end tests
* [ ] Spreadsheet integration tests
* [ ] ML workflow tests

---

## 🚀 Deployment

Possible deployment architecture:

```text
                         Internet
                            │
                            ▼
                       Load Balancer
                            │
                            ▼
                       Frontend
                            │
                            ▼
                         FastAPI
                            │
                ┌───────────┼───────────┐
                ▼           ▼           ▼
            LangGraph     Worker     Database
                │
        ┌───────┼────────┐
        ▼       ▼        ▼
       Jev    Ollama   Sandbox
```

Potential deployment environments:

```text
Docker
Cloud VM
Managed Container Platform
Kubernetes
```

Local deployment should remain available for privacy-focused users.

---

## 🌍 Deployment Modes

### Local Mode

```text
User Computer
│
├── Streamlit / Web UI
├── Ollama
├── Local Data
├── DuckDB
└── Docker Sandbox
```

### Cloud Mode

```text
Cloud
│
├── Frontend
├── FastAPI
├── LangGraph
├── Jev
├── Database
├── Storage
└── Sandbox
```

### Hybrid Mode

```text
User
 ↓
Cloud Application
 ↓
Decision / Orchestration
 ↓
Local Data / Local LLM
```

The exact deployment model depends on privacy, infrastructure, and operational requirements.

---

## 📦 CI/CD

Set up automated development and deployment workflows.

Example:

```text
Git Push
   ↓
CI
   ↓
Tests
   ↓
Security Checks
   ↓
Build Docker Image
   ↓
Deploy
```

Potential tooling:

```text
GitHub Actions
Docker
Container Registry
```

---

## 🔄 Production Self-Healing

The existing self-healing architecture should continue to operate in production.

```text
Request
 ↓
Jev
 ↓
Agent
 ↓
Execution
 ↓
Validation
 ↓
 ┌─────────────┐
 │             │
PASS          FAIL
 │             │
 ↓             ↓
Result       Retry
               ↓
             Agent
```

Production safeguards should limit retries and resource consumption.

---

## 📄 Production Reports

Users should be able to:

* [ ] View reports online
* [ ] Download PDF
* [ ] Download HTML
* [ ] Download Markdown
* [ ] Export Excel
* [ ] Share reports
* [ ] Save report history

---

## 🧑‍💻 Developer API

Provide documentation for developers.

Example:

```text
POST /api/v1/analyze
```

Request:

```json
{
  "dataset_id": "dataset_123",
  "question": "Which region has the highest revenue?"
}
```

Response:

```json
{
  "status": "completed",
  "answer": "North",
  "visualization": "chart_url",
  "report": "report_url"
}
```

---

## 🧪 Phase 10 Success Criteria

Phase 10 will be considered complete when the system can:

1. Support authenticated users.
2. Manage projects and datasets.
3. Run analyses through a production API.
4. Execute AI-generated code safely.
5. Store analysis history.
6. Generate and store reports.
7. Support monitoring and logging.
8. Handle multiple users.
9. Provide API access.
10. Run through a reproducible deployment process.
11. Maintain secure data isolation.
12. Support local, cloud, or hybrid deployment.

---

## Phase 10 Roadmap

* [ ] Production frontend
* [ ] FastAPI backend
* [ ] Authentication
* [ ] Authorization
* [ ] PostgreSQL
* [ ] File/object storage
* [ ] Project management
* [ ] Multi-user support
* [ ] Background workers
* [ ] Docker production setup
* [ ] Monitoring
* [ ] Structured logging
* [ ] Rate limiting
* [ ] API management
* [ ] Usage quotas
* [ ] Developer API
* [ ] CI/CD
* [ ] Production testing
* [ ] Cloud deployment
* [ ] Local deployment
* [ ] Hybrid deployment
* [ ] SaaS capabilities


---

# ⚠️ Limitations

* Local LLMs may generate incorrect SQL or Python.
* Decision quality depends on the Jev configuration and decision schema.
* Complex questions may require multiple analysis steps.
* Very large datasets should primarily be processed using DuckDB.
* Strong isolation should use Docker or another hardened sandbox.
* Local LLM performance depends on available hardware.
* Model capabilities and names can change over time.

---

# 🎯 Project Goal

The goal is to build a **decision-driven AI Data Analyst**, rather than another simple LLM chatbot.

The system separates:

```text
Decision Making
       ↓
      Jev

Generation & Reasoning
       ↓
     Local LLM

Workflow
       ↓
   LangGraph

Data
       ↓
Pandas + DuckDB
```

This architecture makes the system more modular, testable, and suitable for experimenting with different decision models and LLMs.

---

# 🤝 Contributing

Contributions are welcome.

```bash
git checkout -b feature/your-feature
```

Make your changes, add tests, and submit a pull request.

---

# 📄 License

This project is licensed under the **Apache License 2.0**.

See `LICENSE` for details.

---

# 👤 Author

### Premanshu Kumar

**B.Tech Computer Science Engineering — Data Science**

Lovely Professional University

GitHub: **@Premanshu-Kumar**

---

---

# 👥 Contributors

| Contributor | Role |
|-------------|------|
| <a href="https://github.com/Premanshu-Kumar"><img src="https://github.com/Premanshu-Kumar.png" width="50" height="50" style="border-radius:50%"></a> **[Premanshu Kumar](https://github.com/Premanshu-Kumar)** | 🧑‍💻 Project Creator & Lead Developer |
| <a href="https://github.com/apps/devin-ai-integration"><img src="https://avatars.githubusercontent.com/in/932042?s=50&v=4" width="50" height="50" style="border-radius:50%"></a> **[Devin AI](https://github.com/apps/devin-ai-integration)** | 🤖 AI Pair Programmer |
| <img src="https://upload.wikimedia.org/wikipedia/commons/thumb/7/78/Anthropic_logo.svg/50px-Anthropic_logo.svg.png" width="50" height="50" style="border-radius:50%"> **Claude Code** | 🧠 AI Code Contributor — Phase 5 (Validation, Cross-Check, Self-Healing) |

---

# ⭐ Project Summary

> **Ask your data anything. Jev decides the path. Local LLMs generate the solution. LangGraph orchestrates the workflow. The system validates, visualizes, and explains the answer.**

### Built With

**Jev · Ollama · Qwen3-Coder · Qwen3 · LangGraph · DuckDB · Pandas · Plotly · Streamlit · Python**

⭐ If you find this project useful, consider giving it a star!
