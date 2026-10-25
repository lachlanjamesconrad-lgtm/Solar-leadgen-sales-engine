# SunScore Pro (My Solar Plan) ☀️📊
**A Full-Stack Solar Financial Modelling & Lead-Generation Suite**

This repository contains a 4-module Python and Streamlit web application designed to parse raw electricity meter data, simulate intraday grid physics, and model 20-year Discounted Cash Flows (NPV, IRR) for solar and battery assets. 

It functions as both a B2C consumer auditing tool and a B2B sales/lead-generation platform, built to expose unrealistic solar quotes and prove the ROI of premium systems using actual data.

## 🏗️ Architecture & Modules

The suite is divided into four distinct Streamlit applications tailored to different users in the solar funnel:

1. **`lead_gen.py` (B2C Lead Capture & Funnel)**
   * **Purpose:** Top-of-funnel consumer calculator.
   * **Features:** Generates a synthetic 24-hour load profile based on basic household inputs, models baseline solar potential, and gates the detailed ROI behind a Supabase database lead-capture form. Routes users to a paid Stripe checkout for a full engineering audit.
   
2. **`truth.py` (The B2C "Truth Audit")**
   * **Purpose:** An independent auditing tool for consumers with existing solar quotes.
   * **Features:** Ingests raw smart meter CSVs (NEM12 format) to run "The Bullshit Detector," verifying if a salesperson's promised payback period matches the actual physics of the home. Features an Orientation Delta Engine (North vs. East/West yield) and generates hostile leverage PDF reports using the Google Gemini API.

3. **`sales.py` (B2B "Kitchen Table Closer")**
   * **Purpose:** A scenario-modelling tool for premium solar sales representatives.
   * **Features:** Calculates 20-year DCF (NPV, IRR, property valuation uplift) and models green loan amortization. Includes a competitor comparison tab to visualize the 10-year opportunity cost of buying a cheap system locked to zero-export grid throttles.

4. **`app.py` (Enterprise Strategy Engine - v10.0)**
   * **Purpose:** The core modelling engine encompassing both Residential and Commercial assets.
   * **Features:** Evaluates multiple hardware packages simultaneously to generate an ROI Leaderboard. Models Commercial Tariff 50B peak-demand charges and dynamic Energex `STNW1170` export limits. Includes full PDF and AI report generation.

## ⚙️ Core Technical Features

* **Messy CSV Ingestion:** A fault-tolerant Pandas pipeline (`load_and_clean_data`) that handles `utf-8`/`latin-1` encoding errors, strips junk retailer headers, filters out existing solar export registers, and resamples 5-minute/30-minute interval data into standard hourly time series.
* **Physics Engine:** Simulates Gaussian solar yield curves based on system size, panel orientation, and geographic region. Models intraday battery charge/discharge states against grid import limits.
* **Financial Engine (`numpy-financial`):** Calculates system payback periods, Internal Rate of Return (IRR), and Net Present Value (NPV) factoring in hardware degradation, retail energy inflation, and financing costs.
* **API Integrations:** 
  * `google-genai` (Gemini 2.0 Flash) for dynamic audit verdicts.
  * `supabase` for cloud database lead routing.
  * `fpdf` for automated PDF generation with `latin-1` sanitization.

## 🚀 Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/lachlanjamesconrad-lgtm/Solar-leadgen-sales-engine.git](https://github.com/lachlanjamesconrad-lgtm/Solar-leadgen-sales-engine.git)
   cd Solar-leadgen-sales-engine
