import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import StringIO
import numpy_financial as npf # Requires: pip install numpy-financial
from fpdf import FPDF # Requires: pip install fpdf
from google import genai # Requires: pip install google-genai

# -----------------------------------------------------------------------------
# 1. CONFIGURATION & CONSTANTS
# -----------------------------------------------------------------------------
st.set_page_config(page_title="SunScore | The Truth Audit", page_icon="⚖️", layout="wide")

# -- API CONFIG --
# safely load API key from secrets or use placeholder
try:
    API_KEY = st.secrets["GEMINI_API_KEY"] 
except:
    API_KEY = "YOUR_API_KEY_HERE"

# Initialize Client only if key is present to avoid immediate crash
client = None
if API_KEY != "YOUR_API_KEY_HERE":
    try:
        client = genai.Client(api_key=API_KEY)
    except Exception as e:
        pass # Handle gracefully in the function

# -- Energex / Market Constants --
YIELD_MAP = {
    "Brisbane (North)": 4.2,
    "Brisbane (South)": 4.1,
    "Gold Coast": 4.0,
    "Sunshine Coast": 4.3,
    "Ipswich / West": 4.4
}

# Financial Constants
TARIFF_50B_DEMAND = 40.00 # $/kW/month
RETAIL_RATE_RES = 0.34    # $/kWh
RETAIL_RATE_COMM = 0.25   # $/kWh
FEED_IN_RES = 0.05        # $/kWh
CORP_TAX_RATE = 0.25      
RES_INFLATION = 0.03      
DISCOUNT_RATE = 0.07      
WARRANTY_PERIOD = 10      

# -- Standard Packages --
RES_PACKAGES = [
    {"name": "The Investor Special", "kw": 6.6, "bat": 0.0, "cost": 4500},
    {"name": "The Family Standard", "kw": 10.3, "bat": 0.0, "cost": 8500},
    {"name": "Hybrid Entry", "kw": 6.6, "bat": 10.0, "cost": 12500},
    {"name": "The Powerwall Combo", "kw": 10.3, "bat": 13.5, "cost": 19500},
    {"name": "The Grid Defector", "kw": 13.3, "bat": 27.0, "cost": 32000},
]

COMM_PACKAGES = [
    {"name": "Small Biz Offset", "kw": 15.0, "bat": 0.0, "cost": 14000},
    {"name": "Medium Commercial", "kw": 39.0, "bat": 0.0, "cost": 35000},
    {"name": "The Demand Killer", "kw": 39.0, "bat": 20.0, "cost": 55000},
    {"name": "Industrial Scale", "kw": 99.0, "bat": 0.0, "cost": 90000},
]

# -----------------------------------------------------------------------------
# 2. DATA PARSER & PHYSICS ENGINE
# -----------------------------------------------------------------------------

@st.cache_data
def load_and_clean_data(file):
    if file is None: return pd.DataFrame()
    try:
        file.seek(0)
        try:
            content = file.getvalue().decode('utf-8')
        except UnicodeDecodeError:
            content = file.getvalue().decode('latin-1')
        
        # AGL / NEM12 Format Detection
        if "RateTypeDescription" in content or "ProfileReadValue" in content:
            try:
                df = pd.read_csv(StringIO(content))
                df.columns = df.columns.str.strip()
                
                desc_col = next((c for c in df.columns if c in ['RateTypeDescription', 'Rate Type', 'RateType', 'RegisterCode']), None)
                val_col = next((c for c in df.columns if c in ['ProfileReadValue', 'Usage', 'Consumption']), None)
                end_col = next((c for c in df.columns if c in ['EndDate', 'End Date', 'Interval End']), None)
                time_col = end_col 
                
                if time_col and val_col:
                    if desc_col:
                        mask = ~df[desc_col].astype(str).str.lower().str.contains('solar|export|feed', na=False)
                        df = df[mask]
                    
                    df['Time'] = pd.to_datetime(df[time_col], dayfirst=True, errors='coerce')
                    df = df.dropna(subset=['Time'])
                    df['Usage_kWh'] = pd.to_numeric(df[val_col], errors='coerce').fillna(0)
                    
                    df_grouped = df.groupby('Time')['Usage_kWh'].sum().reset_index()
                    df_grouped = df_grouped.set_index('Time').sort_index()
                    return df_grouped[['Usage_kWh']].resample('h').sum().fillna(0)
            except:
                pass 

        # Generic CSV Fallback
        df = pd.read_csv(StringIO(content))
        col_map = {
            'Usage': 'Usage_kWh', 'Consumption': 'Usage_kWh', 'Quantity': 'Usage_kWh', 
            'Start Time': 'Time', 'StartDate': 'Time', 'Interval End': 'Time', 'Date': 'Time'
        }
        df.rename(columns=lambda x: col_map.get(x, x), inplace=True)
        
        if 'Time' in df.columns and 'Usage_kWh' in df.columns:
            df['Time'] = pd.to_datetime(df['Time'], dayfirst=True, errors='coerce')
            df = df.dropna(subset=['Time']).set_index('Time').sort_index()
            df['Usage_kWh'] = pd.to_numeric(df['Usage_kWh'], errors='coerce').fillna(0)
            return df[['Usage_kWh']].resample('h').sum().fillna(0)

        # --- NEW PARSING CAPABILITIES FALLBACK A (Silent failure handler) ---
        try:
            df2 = pd.read_csv(StringIO(content))
            broad_map = {'Date/Time': 'Time', 'kWh': 'Usage_kWh'}
            df2.rename(columns=lambda x: broad_map.get(x, x), inplace=True)
            if 'Time' in df2.columns and 'Usage_kWh' in df2.columns:
                df2['Time'] = pd.to_datetime(df2['Time'], format="mixed", dayfirst=True, errors='coerce')
                if df2['Time'].isna().all():
                    df2['Time'] = pd.to_datetime(df2['Time'], errors='coerce')
                df2 = df2.dropna(subset=['Time']).set_index('Time').sort_index()
                df2['Usage_kWh'] = pd.to_numeric(df2['Usage_kWh'], errors='coerce').fillna(0)
                return df2[['Usage_kWh']].resample('h').sum().fillna(0)
        except Exception:
            pass

    except Exception as e:
        # --- NEW PARSING CAPABILITIES FALLBACK B (Junk headers & C parser errors) ---
        try:
            lines = content.splitlines()
            header_idx = -1
            for i, line in enumerate(lines[:30]):
                if 'Usage' in line or 'kWh' in line or 'Consumption' in line or 'Date' in line or 'Quantity' in line:
                    header_idx = i
                    break
            if header_idx != -1:
                df3 = pd.read_csv(StringIO(content), skiprows=header_idx)
                col_map_ext = {
                    'Usage': 'Usage_kWh', 'Consumption': 'Usage_kWh', 'Quantity': 'Usage_kWh', 'kWh': 'Usage_kWh',
                    'Start Time': 'Time', 'StartDate': 'Time', 'Interval End': 'Time', 'Date': 'Time', 'Date/Time': 'Time'
                }
                df3.rename(columns=lambda x: col_map_ext.get(x, x), inplace=True)
                if 'Time' in df3.columns and 'Usage_kWh' in df3.columns:
                    df3['Time'] = pd.to_datetime(df3['Time'], format="mixed", dayfirst=True, errors='coerce')
                    df3 = df3.dropna(subset=['Time']).set_index('Time').sort_index()
                    df3['Usage_kWh'] = pd.to_numeric(df3['Usage_kWh'], errors='coerce').fillna(0)
                    return df3[['Usage_kWh']].resample('h').sum().fillna(0)
        except Exception:
            pass

        st.error(f"Parser Error: {e}")
        return pd.DataFrame()
    return pd.DataFrame()

def calculate_solar_yield(system_size_kw, efficiency=0.85, region_yield=4.2):
    hours = np.arange(24)
    # Gaussian bell curve for solar production
    generation_profile = np.exp(-((hours - 12)**2) / (2 * 2.5**2))
    daily_production = system_size_kw * region_yield * efficiency
    scaling_factor = daily_production / np.sum(generation_profile)
    return generation_profile * scaling_factor

def run_simulation(df, system_kw, battery_kwh, export_limit_kw, region_yield):
    sim = df.copy()
    hourly_gen = calculate_solar_yield(system_kw, region_yield=region_yield)
    days = len(sim) // 24
    if days == 0: return sim
    
    # FIX: Map directly to timestamp hour to prevent midnight solar offset
    sim['Solar_Gen_kWh'] = hourly_gen[sim.index.hour]
    
    sim['Battery_State'] = 0.0
    battery_charge = 0.0
    grid_export = []
    grid_import = []
    
    for i in range(len(sim)):
        gen = sim['Solar_Gen_kWh'].iloc[i]
        load = sim['Usage_kWh'].iloc[i]
        net = gen - load
        
        if net > 0:
            can_charge = battery_kwh - battery_charge
            charge_amount = min(net, can_charge)
            battery_charge += charge_amount
            remainder = net - charge_amount
            export = min(remainder, export_limit_kw)
            grid_export.append(export)
            grid_import.append(0)
        else:
            needed = abs(net)
            discharge_amount = min(needed, battery_charge)
            battery_charge -= discharge_amount
            import_kwh = needed - discharge_amount
            grid_import.append(import_kwh)
            grid_export.append(0)
            
    sim['Grid_Export_kWh'] = grid_export
    sim['Grid_Import_kWh'] = grid_import
    return sim

# -----------------------------------------------------------------------------
# 3. FINANCIAL ENGINES
# -----------------------------------------------------------------------------

def calculate_dcf(annual_savings, cost, years=20, financing_setup=None):
    cash_flows = []
    
    # Year 0: If financed, no upfront cost. If cash, negative cost.
    if financing_setup:
        cash_flows.append(0) 
    else:
        cash_flows.append(-cost)

    loan_payment = 0
    if financing_setup:
        r = financing_setup['rate'] / 12
        n = financing_setup['term'] * 12
        if r > 0:
             monthly_payment = cost * (r * (1 + r)**n) / ((1 + r)**n - 1)
             loan_payment = monthly_payment * 12
    
    for i in range(1, years + 1):
        inflated_savings = annual_savings * ((1 + RES_INFLATION) ** (i-1))
        current_year_net = inflated_savings
        
        # Deduct loan payment if within term
        if financing_setup and i <= financing_setup['term']:
            current_year_net -= loan_payment
            
        cash_flows.append(current_year_net)
    
    npv = npf.npv(DISCOUNT_RATE, cash_flows)
    try:
        irr = npf.irr(cash_flows)
        if np.isnan(irr):
            irr = 0.0
    except:
        irr = 0.0
    
    # Valuation Uplift (Unlevered NPV used for asset valuation)
    unlevered_npv = npf.npv(DISCOUNT_RATE, [-cost] + [annual_savings * ((1 + RES_INFLATION) ** (i-1)) for i in range(1, years+1)])
    valuation_uplift = unlevered_npv + cost 
    
    return npv, irr, valuation_uplift, cash_flows

def calc_commercial_economics(sim_df, system_cost, finance_config=None):
    if sim_df.empty: return {}
    
    sim_df['Month'] = sim_df.index.to_period('M')
    monthly_peaks_orig = sim_df.groupby('Month')['Usage_kWh'].max()
    monthly_peaks_new = sim_df.groupby('Month')['Grid_Import_kWh'].max()
    
    demand_reduction = (monthly_peaks_orig.mean() - monthly_peaks_new.mean())
    annual_demand_savings = demand_reduction * TARIFF_50B_DEMAND * 12
    
    total_import_orig = sim_df['Usage_kWh'].sum()
    total_import_new = sim_df['Grid_Import_kWh'].sum()
    usage_savings = (total_import_orig - total_import_new) * RETAIL_RATE_COMM
    
    total_annual_benefit = annual_demand_savings + usage_savings
    simple_payback = system_cost / total_annual_benefit if total_annual_benefit > 0 else 99
    
    npv, irr, val_uplift, cashflows = calculate_dcf(total_annual_benefit, system_cost, years=20, financing_setup=finance_config)
    npv_warranty, _, _, _ = calculate_dcf(total_annual_benefit, system_cost, years=WARRANTY_PERIOD, financing_setup=finance_config)
    
    return {
        "Annual_Benefit": total_annual_benefit,
        "Payback_Years": simple_payback,
        "Demand_Reduction_kW": demand_reduction,
        "NPV": npv,
        "NPV_Warranty": npv_warranty,
        "IRR": irr,
        "Valuation_Uplift": val_uplift,
        "Cashflows": cashflows
    }

def calc_residential_economics(sim_df, system_cost, finance_config=None):
    if sim_df.empty: return {}
    
    # Calculate exactly how many years of data we are looking at
    days_in_data = len(sim_df) / 24
    annual_multiplier = 365.25 / days_in_data if days_in_data > 0 else 1.0
    
    # Apply the multiplier so the totals reflect a single 12-month period
    import_cost_orig = (sim_df['Usage_kWh'].sum() * RETAIL_RATE_RES) * annual_multiplier
    import_cost_new = (sim_df['Grid_Import_kWh'].sum() * RETAIL_RATE_RES) * annual_multiplier
    export_credit = (sim_df['Grid_Export_kWh'].sum() * FEED_IN_RES) * annual_multiplier
    
    new_bill = import_cost_new - export_credit
    savings = import_cost_orig - new_bill
    payback = system_cost / savings if savings > 0 else 99
    bill_offset = (1 - (new_bill / import_cost_orig)) * 100 if import_cost_orig > 0 else 0
    
    npv, irr, val_uplift, cashflows = calculate_dcf(savings, system_cost, years=20, financing_setup=finance_config)
    npv_warranty, _, _, _ = calculate_dcf(savings, system_cost, years=WARRANTY_PERIOD, financing_setup=finance_config)
    
    return {
        "Annual_Savings": savings,
        "Payback_Years": payback,
        "Independence": bill_offset,
        "NPV": npv,
        "NPV_Warranty": npv_warranty,
        "IRR": irr,
        "Valuation_Uplift": val_uplift,
        "Cashflows": cashflows
    }

# -----------------------------------------------------------------------------
# 4. REPORT GENERATION ENGINE (PDF & AI)
# -----------------------------------------------------------------------------
def generate_ai_commentary(stats, mode):
    """
    Generates a verdict using Gemini.
    Crucial: 'stats' keys must match the Display Columns from the DataFrame.
    """
    if not client or API_KEY == "YOUR_API_KEY_HERE":
        return "AI Commentary Unavailable. The numbers speak for themselves: verify payback and NPV match your goals."

    # Map keys safely based on mode
    if mode == "Residential (Home)":
        savings_val = stats.get('Annual Savings', 0)
        payback_val = stats.get('Payback (Yrs)', 99)
        profit_val = stats.get('Lifetime NPV', 0)
    else:
        savings_val = stats.get('Annual Benefit', 0)
        payback_val = stats.get('Payback (Yrs)', 99)
        profit_val = stats.get('Valuation Uplift', 0)
    
    cost_val = stats.get('Cost', 0)

    prompt = f"""
    You are a blunt, honest solar auditor writing a report for a {mode} client.
    Data:
    - System Cost: ${cost_val}
    - Annual Benefit: ${savings_val:.0f}
    - Payback Period: {payback_val:.1f} Years
    - Long Term Value: ${profit_val:.0f}
    
    Write a 3-sentence verdict.
    Sentence 1: Comment on the payback speed (Fast <4yrs, Avg 4-7yrs, Slow >7yrs).
    Sentence 2: Comment on the long-term wealth/value creation.
    Sentence 3: Give a final "Buy", "Consider", or "Avoid" recommendation.
    Keep it professional but direct.
    """
    try:
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return response.text
    except Exception as e:
        return f"AI Connection Failed ({str(e)}). Manual Verdict: Solid financials."

def create_pdf(metrics, mode, system_name, ai_text):
    """
    Generates a PDF Report. 
    Fixes: Uses bytes() output for modern fpdf2 compatibility and latin-1 sanitization.
    """
    safe_ai_text = str(ai_text).encode('latin-1', 'replace').decode('latin-1')
    safe_sys_name = str(system_name).encode('latin-1', 'replace').decode('latin-1')
    safe_mode = str(mode).encode('latin-1', 'replace').decode('latin-1')
    
    pdf = FPDF()
    pdf.add_page()
    
    # Title
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, f"SunScore {safe_mode} Audit", 0, 1, 'C')
    
    # Executive Summary
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, f"Recommended Strategy: {safe_sys_name}", 0, 1)
    
    # AI Verdict Box
    pdf.set_font("Arial", 'I', 11)
    pdf.set_text_color(50, 50, 50)
    pdf.multi_cell(0, 8, f"Auditor's Verdict:\n{safe_ai_text}")
    pdf.ln(5)
    
    # The Numbers
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(100, 10, "Metric", 1)
    pdf.cell(0, 10, "Value", 1, 1)
    
    pdf.set_font("Arial", '', 12)
    
    # Logic to handle keys safely
    if mode == "Residential (Home)":
         pdf.cell(100, 10, "Annual Savings", 1)
         pdf.cell(0, 10, f"${metrics.get('Annual Savings',0):,.0f}", 1, 1)
         
         pdf.cell(100, 10, "Payback Period", 1)
         pdf.cell(0, 10, f"{metrics.get('Payback (Yrs)',99):.1f} Years", 1, 1)
         
         pdf.cell(100, 10, "20-Year Net Value (NPV)", 1)
         pdf.cell(0, 10, f"${metrics.get('Lifetime NPV',0):,.0f}", 1, 1)
         
         pdf.cell(100, 10, "Grid Independence", 1)
         pdf.cell(0, 10, f"{metrics.get('Independence (%)',0):.1f}%", 1, 1)
    else:
         pdf.cell(100, 10, "Annual Benefit", 1)
         pdf.cell(0, 10, f"${metrics.get('Annual Benefit',0):,.0f}", 1, 1)
         
         pdf.cell(100, 10, "Payback Period", 1)
         pdf.cell(0, 10, f"{metrics.get('Payback (Yrs)',99):.1f} Years", 1, 1)
         
         pdf.cell(100, 10, "Valuation Uplift", 1)
         pdf.cell(0, 10, f"${metrics.get('Valuation Uplift',0):,.0f}", 1, 1)
         
         pdf.cell(100, 10, "Demand Reduction", 1)
         pdf.cell(0, 10, f"{metrics.get('Demand Reduction (kW)',0):.1f} kW", 1, 1)

    pdf.ln(10)
    pdf.set_font("Arial", 'I', 8)
    pdf.cell(0, 10, "Generated by SunScore Analytics. This is a model, not a financial guarantee.", 0, 1, 'C')
    
    return bytes(pdf.output())

@st.cache_data
def generate_scenario_results(df, app_mode, is_financed, finance_config, sys_size, batt_size, sys_cost, export_limit, region_yield):
    scenarios = RES_PACKAGES if app_mode == "Residential (Home)" else COMM_PACKAGES
    results = []
    
    custom_pkg = {"name": "Your Custom Build", "kw": sys_size, "bat": batt_size, "cost": sys_cost}
    all_scenarios = scenarios + [custom_pkg]
    
    for pkg in all_scenarios:
        sim_res = run_simulation(df, pkg['kw'], pkg['bat'], export_limit, region_yield)
        conf_str = f"{pkg['kw']}kW Solar"
        if pkg['bat'] > 0: conf_str += f" + {pkg['bat']}kWh Batt"
        
        if app_mode == "Residential (Home)":
            econ = calc_residential_economics(sim_res, pkg['cost'], finance_config)
            results.append({
                "System": pkg['name'],
                "Configuration": conf_str,
                "Cost": pkg['cost'],
                "Payback (Yrs)": econ['Payback_Years'],
                "Annual Savings": econ['Annual_Savings'],
                "ROI (%)": (econ['Annual_Savings']/pkg['cost'])*100 if pkg['cost']>0 else 0,
                "Independence (%)": econ['Independence'],
                "Warranty NPV": econ['NPV_Warranty'],
                "Lifetime NPV": econ['NPV']
            })
        else:
            econ = calc_commercial_economics(sim_res, pkg['cost'], finance_config)
            results.append({
                "System": pkg['name'],
                "Configuration": conf_str,
                "Cost": pkg['cost'],
                "Payback (Yrs)": econ['Payback_Years'],
                "Annual Benefit": econ['Annual_Benefit'],
                "IRR (%)": econ['IRR'] * 100 if econ['IRR'] else 0,
                "Demand Reduction (kW)": econ['Demand_Reduction_kW'],
                "Warranty NPV": econ['NPV_Warranty'],
                "Valuation Uplift": econ['Valuation_Uplift']
            })
    
    return pd.DataFrame(results), all_scenarios

# -----------------------------------------------------------------------------
# 5. THE UI (Streamlit)
# -----------------------------------------------------------------------------

# Sidebar Controls
with st.sidebar:
    st.image("https://img.icons8.com/color/96/solar-panel.png", width=50)
    st.title("SunScore Pro")
    st.caption("v10.0 Production (Fixed)")
    st.markdown("---")
    
    app_mode = st.radio("Audit Mode", ["Residential (Home)", "Commercial (Business)"])
    
    selected_region = st.selectbox("📍 Region / Zone", list(YIELD_MAP.keys()))
    region_yield = YIELD_MAP[selected_region]
    st.caption(f"Yield Factor: {region_yield} kWh/kW")

    st.markdown("### 💸 Financing Options")
    is_financed = st.checkbox("Apply Financing?")
    finance_config = None
    if is_financed:
        rate = st.number_input("Interest Rate (%)", 5.0, 15.0, 7.9, 0.1)
        term = st.slider("Loan Term (Years)", 3, 10, 5)
        finance_config = {'rate': rate/100, 'term': term}
    
    st.markdown("### 🔧 Custom Scenario")
    sys_size = st.number_input("Solar Size (kW)", value=6.6 if app_mode == "Residential (Home)" else 39.0)
    batt_size = st.number_input("Battery (kWh)", value=0.0)
    sys_cost = st.number_input("System Cost ($)", value=6000 if app_mode == "Residential (Home)" else 35000)
    
    st.markdown("### ⚡ Grid Constraints")
    export_limit = st.selectbox("Export Limit", [5.0, 1.5, 0.0, 15.0, 30.0], index=0 if app_mode == "Residential (Home)" else 2)
    
    st.markdown("---")
    st.markdown("### 📄 Client Report")

    st.info("Upload CSV (NEM12 or Retailer) to begin.")

# Main Interface
st.title(f"📊 {app_mode} Strategy Engine")
st.markdown(f"**Location:** {selected_region} | **Tariff:** {'Standard Res' if app_mode == 'Residential (Home)' else 'Tariff 50B (Demand)'}")

uploaded_file = st.file_uploader("Upload Energy Data (CSV)", type=['csv'])

if uploaded_file is not None:
    df = load_and_clean_data(uploaded_file)
    
    if df.empty:
        st.error("❌ Could not read CSV. Ensure it has a 'Usage' or 'Consumption' column and a Date/Time column.")
    else:
        # ---------------------------------------------------------------------
        # TABBED INTERFACE
        # ---------------------------------------------------------------------
        tab1, tab2, tab3 = st.tabs(["🏆 The Strategy Leaderboard", "📈 Deep Financials", "🔧 Custom Scenario"])
        
        # --- PRE-CALCULATE SCENARIOS ---
        results_df, all_scenarios = generate_scenario_results(
            df, app_mode, is_financed, finance_config, sys_size, batt_size, sys_cost, export_limit, region_yield
        )

        # ---------------------------------------------------------------------
        # TAB 1: THE STRATEGY LEADERBOARD
        # ---------------------------------------------------------------------
        with tab1:
            st.header("Optimal Configuration Finder")
            if is_financed:
                st.info(f"🏦 **Financing Applied:** {finance_config['term']} Years @ {finance_config['rate']*100:.1f}%.")

            if app_mode == "Residential (Home)":
                best_payback = results_df.loc[results_df['Payback (Yrs)'].idxmin()]
                best_independence = results_df.loc[results_df['Independence (%)'].idxmax()]
                
                c1, c2 = st.columns(2)
                c1.success(f"💰 **Best Financial ROI:** {best_payback['System']}")
                c1.metric("Payback", f"{best_payback['Payback (Yrs)']:.1f} Years", f"ROI: {best_payback['ROI (%)']:.1f}%")
                c2.info(f"🔋 **Max Independence:** {best_independence['System']}")
                c2.metric("Grid Independence", f"{best_independence['Independence (%)']:.1f}%", f"Bill: -${best_independence['Annual Savings']:,.0f}")
                
                st.dataframe(
                    results_df.style.format({
                        "Cost": "${:,.0f}", "Payback (Yrs)": "{:.1f}", "Annual Savings": "${:,.0f}",
                        "ROI (%)": "{:.1f}%", "Independence (%)": "{:.1f}%", "Warranty NPV": "${:,.0f}", "Lifetime NPV": "${:,.0f}"
                    }).background_gradient(subset=['ROI (%)'], cmap='Greens'), use_container_width=True
                )
            else:
                best_irr = results_df.loc[results_df['IRR (%)'].idxmax()]
                best_cash = results_df.loc[results_df['Annual Benefit'].idxmax()]
                
                c1, c2 = st.columns(2)
                c1.success(f"📈 **Highest IRR:** {best_irr['System']}")
                c1.metric("Internal Rate of Return", f"{best_irr['IRR (%)']:.1f}%", f"Payback: {best_irr['Payback (Yrs)']:.1f} Yrs")
                c2.info(f"💵 **Max Cashflow:** {best_cash['System']}")
                c2.metric("Annual Benefit", f"${best_cash['Annual Benefit']:,.0f}", f"Valuation Uplift: ${best_cash['Valuation Uplift']:,.0f}")
                
                st.dataframe(
                    results_df.style.format({
                        "Cost": "${:,.0f}", "Payback (Yrs)": "{:.1f}", "Annual Benefit": "${:,.0f}",
                        "IRR (%)": "{:.1f}%", "Demand Reduction (kW)": "{:.1f}", "Warranty NPV": "${:,.0f}", "Valuation Uplift": "${:,.0f}"
                    }).background_gradient(subset=['IRR (%)'], cmap='Greens'), use_container_width=True
                )

        # ---------------------------------------------------------------------
        # TAB 2: DEEP FINANCIALS
        # ---------------------------------------------------------------------
        with tab2:
            st.header("Financial & Valuation Modeling")
            selected_sys_name = st.selectbox("Select System for Deep Dive", results_df['System'])
            sel_config = next(item for item in all_scenarios if item["name"] == selected_sys_name)
            sel_sim = run_simulation(df, sel_config['kw'], sel_config['bat'], export_limit, region_yield)
            
            if app_mode == "Residential (Home)":
                econ = calc_residential_economics(sel_sim, sel_config['cost'], finance_config)
                col1, col2, col3 = st.columns(3)
                col1.metric("Lifetime NPV (20yr)", f"${econ['NPV']:,.0f}")
                col2.metric("Warranty NPV (10yr)", f"${econ['NPV_Warranty']:,.0f}")
                col3.metric("Property Uplift", f"${econ['Valuation_Uplift']:,.0f}")
                
                subject = f"Quote Request: {selected_sys_name}"
                body = f"I would like a quote for:\nSystem: {selected_sys_name}\nSolar: {sel_config['kw']}kW\nBattery: {sel_config['bat']}kWh"
                st.markdown(f'<a href="mailto:?subject={subject}&body={body}" target="_blank"><button style="background-color:#4CAF50;color:white;padding:10px;border:none;border-radius:4px;">✉️ Request Quote</button></a>', unsafe_allow_html=True)
                st.area_chart(pd.DataFrame(np.cumsum(econ['Cashflows']), columns=["Bank Balance"]))
                
            else:
                econ = calc_commercial_economics(sel_sim, sel_config['cost'], finance_config)
                col1, col2, col3 = st.columns(3)
                col1.metric("Business Valuation Uplift", f"${econ['Valuation_Uplift']:,.0f}")
                col2.metric("Warranty NPV (10yr)", f"${econ['NPV_Warranty']:,.0f}")
                col3.metric("IRR", f"{econ['IRR']*100:.1f}%")
                
                subject = f"Commercial Quote: {selected_sys_name}"
                body = f"I require a commercial proposal for:\nSystem: {selected_sys_name}\nCapacity: {sel_config['kw']}kW"
                st.markdown(f'<a href="mailto:?subject={subject}&body={body}" target="_blank"><button style="background-color:#FF5722;color:white;padding:10px;border:none;border-radius:4px;">🏭 Request Proposal</button></a>', unsafe_allow_html=True)
                
                chart_data = sel_sim.iloc[0:24*7].copy()
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Usage_kWh'], name="Original Load", line=dict(color='gray', dash='dot')))
                fig.add_trace(go.Scatter(x=chart_data.index, y=chart_data['Grid_Import_kWh'], name="New Load Profile", line=dict(color='red')))
                st.plotly_chart(fig, use_container_width=True)

        # ---------------------------------------------------------------------
        # TAB 3: CUSTOM SCENARIO
        # ---------------------------------------------------------------------
        with tab3:
            st.header("Sandbox Simulation")
            st.markdown("Use the sidebar controls to tweak this custom model.")
            custom_sim = run_simulation(df, sys_size, batt_size, export_limit, region_yield)
            
            # Simple chart
            slice_df = custom_sim.iloc[0:min(len(custom_sim), 24*7)]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=slice_df.index, y=slice_df['Usage_kWh'], name="Load", line=dict(color='gray')))
            fig.add_trace(go.Scatter(x=slice_df.index, y=slice_df['Solar_Gen_kWh'], name="Solar", fill='tozeroy', line=dict(color='orange')))
            fig.add_trace(go.Scatter(x=slice_df.index, y=slice_df['Grid_Import_kWh'], name="Import", line=dict(color='red')))
            st.plotly_chart(fig, use_container_width=True)

        # ---------------------------------------------------------------------
        # GENERATE PDF LOGIC
        # ---------------------------------------------------------------------
        with st.sidebar:
            if st.button("📝 Generate PDF Report"):
                if not results_df.empty:
                    # FIX: Grab the user's selected system from Tab 2 instead of hardcoding row 0
                    matched_rows = results_df[results_df['System'] == selected_sys_name]
                    best_sys = matched_rows.iloc[0] if not matched_rows.empty else results_df.iloc[0]
                    
                    with st.spinner("AI is analyzing & writing report..."):
                        try:
                            ai_verdict = generate_ai_commentary(best_sys, app_mode)
                            pdf_data = create_pdf(best_sys, app_mode, best_sys['System'], ai_verdict)
                            
                            st.download_button(
                                label="⬇️ Download Official Report",
                                data=pdf_data,
                                file_name="SunScore_Audit.pdf",
                                mime="application/pdf"
                            )
                            st.success("Report Ready!")
                        except Exception as e:
                            st.error(f"Failed to compile PDF Report: {str(e)}")
                else:
                    st.warning("⚠️ Run the simulation first before generating a report.")

else:
    st.info("👋 Welcome to the SunScore Strategy Engine. Please upload a CSV file.")
