import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import StringIO
import numpy_financial as npf 
from fpdf import FPDF 
from google import genai 

# -----------------------------------------------------------------------------
# 1. CORE CONFIG & CONSTANTS (PRESERVED)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="My Solar Plan | The Truth Audit", page_icon="⚖️", layout="wide")

# Initialize Session State for Tab 3 PDF generation
if 'qc_data' not in st.session_state:
    st.session_state['qc_data'] = None

try:
    API_KEY = st.secrets["GEMINI_API_KEY"] 
except:
    API_KEY = "YOUR_API_KEY_HERE"

client = None
if API_KEY != "YOUR_API_KEY_HERE":
    try:
        client = genai.Client(api_key=API_KEY)
    except Exception as e:
        pass 

YIELD_MAP = {
    "Brisbane (North)": 4.2,
    "Brisbane (South)": 4.1,
    "Gold Coast": 4.0,
    "Sunshine Coast": 4.3,
    "Ipswich / West": 4.4
}

TARIFF_50B_DEMAND = 40.00 
RETAIL_RATE_RES = 0.34    
RETAIL_RATE_COMM = 0.25   
FEED_IN_RES = 0.05        
CORP_TAX_RATE = 0.25      
RES_INFLATION = 0.03      
DISCOUNT_RATE = 0.07      
WARRANTY_PERIOD = 10      

# -----------------------------------------------------------------------------
# 2. DATA PARSER & PHYSICS ENGINE (PRESERVED)
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
        
        if "RateTypeDescription" in content or "ProfileReadValue" in content:
            try:
                df = pd.read_csv(StringIO(content))
                df.columns = df.columns.str.strip()
                desc_col = next((c for c in df.columns if c in ['RateTypeDescription', 'Rate Type', 'RateType', 'RegisterCode']), None)
                val_col = next((c for c in df.columns if c in ['ProfileReadValue', 'Usage', 'Consumption']), None)
                time_col = next((c for c in df.columns if c in ['EndDate', 'End Date', 'Interval End']), None)
                
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
    grid_export, grid_import = [], []
    
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
# 3. FINANCIAL ENGINES & PDF GENERATOR (PRESERVED)
# -----------------------------------------------------------------------------
def calculate_dcf(annual_savings, cost, years=20, financing_setup=None):
    cash_flows = [0] if financing_setup else [-cost]
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
        if financing_setup and i <= financing_setup['term']:
            current_year_net -= loan_payment
        cash_flows.append(current_year_net)
    
    npv = npf.npv(DISCOUNT_RATE, cash_flows)
    try:
        irr = npf.irr(cash_flows) if cash_flows else 0.0
        if np.isnan(irr):
            irr = 0.0
    except Exception:
        irr = 0.0
        
    unlevered_npv = npf.npv(DISCOUNT_RATE, [-cost] + [annual_savings * ((1 + RES_INFLATION) ** (i-1)) for i in range(1, years+1)])
    return npv, irr, unlevered_npv + cost, cash_flows

def calc_residential_economics(sim_df, system_cost, finance_config=None):
    if sim_df.empty: return {}
    
    # FIX: Annualize based on exact number of days in uploaded CSV
    days_in_data = len(sim_df) / 24
    annual_multiplier = 365.25 / days_in_data if days_in_data > 0 else 1.0
    
    import_cost_orig = (sim_df['Usage_kWh'].sum() * RETAIL_RATE_RES) * annual_multiplier
    import_cost_new = (sim_df['Grid_Import_kWh'].sum() * RETAIL_RATE_RES) * annual_multiplier
    export_credit = (sim_df['Grid_Export_kWh'].sum() * FEED_IN_RES) * annual_multiplier
    
    new_bill = import_cost_new - export_credit
    savings = import_cost_orig - new_bill
    payback = system_cost / savings if savings > 0 else 99
    bill_offset = (1 - (new_bill / import_cost_orig)) * 100 if import_cost_orig > 0 else 0
    npv, irr, val_uplift, cashflows = calculate_dcf(savings, system_cost, years=20, financing_setup=finance_config)
    npv_warranty, _, _, _ = calculate_dcf(savings, system_cost, years=WARRANTY_PERIOD, financing_setup=finance_config)
    
    return {"Annual_Savings": savings, "Payback_Years": payback, "Independence": bill_offset, "NPV": npv, "NPV_Warranty": npv_warranty, "IRR": irr, "Valuation_Uplift": val_uplift, "Cashflows": cashflows}

def generate_ai_commentary(stats, mode):
    if not client or API_KEY == "YOUR_API_KEY_HERE": return "Manual Verdict: Proceed based on data."
    savings_val, payback_val, profit_val, cost_val = stats.get('Annual Savings', 0), stats.get('Payback (Yrs)', 99), stats.get('Lifetime NPV', 0), stats.get('Cost', 0)
    prompt = f"You are a blunt, honest solar auditor writing a report for a {mode} client. Data: Cost ${cost_val}, Benefit ${savings_val:.0f}, Payback {payback_val:.1f} Yrs, NPV ${profit_val:.0f}. Write 3 sentences. 1: Payback speed. 2: Long term value. 3: Final Buy/Consider/Avoid. Keep it blunt."
    try: return client.models.generate_content(model="gemini-2.0-flash", contents=prompt).text
    except: return "AI Connection Failed. Manual Verdict: Solid financials."

def create_pdf(metrics, mode, system_name, ai_text):
    # FIX: Sanitize strings to prevent FPDF latin-1 Unicode crashes
    safe_ai_text = str(ai_text).encode('latin-1', 'replace').decode('latin-1')
    safe_sys_name = str(system_name).encode('latin-1', 'replace').decode('latin-1')
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(0, 15, f"My Solar Plan | The Truth Audit", 0, 1, 'C')
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, f"Strategy Assessed: {safe_sys_name}", 0, 1)
    pdf.set_font("Arial", 'I', 11)
    pdf.multi_cell(0, 8, f"Auditor's Verdict:\n{safe_ai_text}")
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(100, 10, "Metric", 1); pdf.cell(0, 10, "Value", 1, 1)
    pdf.set_font("Arial", '', 12)
    pdf.cell(100, 10, "Annual Savings", 1); pdf.cell(0, 10, f"${metrics.get('Annual Savings',0):,.0f}", 1, 1)
    pdf.cell(100, 10, "Payback Period", 1); pdf.cell(0, 10, f"{metrics.get('Payback (Yrs)',99):.1f} Years", 1, 1)
    pdf.cell(100, 10, "20-Year Net Value (NPV)", 1); pdf.cell(0, 10, f"${metrics.get('Lifetime NPV',0):,.0f}", 1, 1)
    pdf.ln(10)
    pdf.set_font("Arial", 'I', 8)
    pdf.cell(0, 10, "Generated by My Solar Plan Analytics. This is a model, not a financial guarantee.", 0, 1, 'C')
    return bytes(pdf.output())

# -----------------------------------------------------------------------------
# 4. TIER 2/3 MODULAR WRAPPERS (THE DELTA ENGINE)
# -----------------------------------------------------------------------------
def calculate_directional_yield(system_size_kw, direction="North", efficiency=0.85, region_yield=4.2):
    hours = np.arange(24)
    if direction == "North":
        peak, factor = 12.0, 1.0
    elif direction == "West (Afternoon Heavy)":
        peak, factor = 15.0, 0.88 
    elif direction == "East (Morning Heavy)":
        peak, factor = 9.0, 0.88
    elif direction == "Split (East/West)":
        return calculate_directional_yield(system_size_kw/2, "East (Morning Heavy)", efficiency, region_yield) + \
               calculate_directional_yield(system_size_kw/2, "West (Afternoon Heavy)", efficiency, region_yield)
    else:
        peak, factor = 12.0, 1.0
        
    generation_profile = np.exp(-((hours - peak)**2) / (2 * 2.5**2))
    daily_production = system_size_kw * (region_yield * factor) * efficiency
    scaling_factor = daily_production / np.sum(generation_profile)
    return generation_profile * scaling_factor

def run_directional_simulation(df, system_kw, battery_kwh, export_limit_kw, region_yield, direction="North"):
    sim = df.copy()
    hourly_gen = calculate_directional_yield(system_kw, direction, region_yield=region_yield)
    days = len(sim) // 24
    if days == 0: return sim
    
    # FIX: Map directly to timestamp hour to prevent midnight solar offset
    sim['Solar_Gen_kWh'] = hourly_gen[sim.index.hour]
    sim['Battery_State'] = 0.0
    battery_charge = 0.0
    grid_export, grid_import = [], []
    
    for i in range(len(sim)):
        gen = sim['Solar_Gen_kWh'].iloc[i]
        load = sim['Usage_kWh'].iloc[i]
        net = gen - load
        if net > 0:
            can_charge = battery_kwh - battery_charge
            charge_amount = min(net, can_charge)
            battery_charge += charge_amount
            export = min(net - charge_amount, export_limit_kw)
            grid_export.append(export); grid_import.append(0)
        else:
            needed = abs(net)
            discharge_amount = min(needed, battery_charge)
            battery_charge -= discharge_amount
            grid_import.append(needed - discharge_amount); grid_export.append(0)
            
    sim['Grid_Export_kWh'] = grid_export
    sim['Grid_Import_kWh'] = grid_import
    return sim

# -----------------------------------------------------------------------------
# 5. B2C TRUTH AUDIT UI
# -----------------------------------------------------------------------------
st.title("⚖️ My Solar Plan: The Truth Audit")
st.markdown("We don't sell solar. We expose bad quotes. Upload your interval data to find out if your salesperson is lying to you.")

with st.sidebar:
    st.header("1. Core Setup")
    selected_region = st.selectbox("📍 Region / Zone", list(YIELD_MAP.keys()))
    region_yield = YIELD_MAP[selected_region]
    
    st.header("2. STNW1170 Grid Throttler")
    st.markdown("Energex dynamically limits exports. Ensure your quote accounts for this.")
    export_limit = st.slider("Export Limit (kW)", 0.0, 10.0, 5.0, 1.5)
    
    uploaded_file = st.file_uploader("Upload CSV Data", type=['csv'])

if uploaded_file is not None:
    df = load_and_clean_data(uploaded_file)
    if not df.empty:
        tab1, tab2, tab3 = st.tabs(["🚨 The Bullshit Detector", "🏠 Roof Optimizer (Delta)", "📄 Official Report"])
        
        # --- TAB 1: QUOTE CHECKER ---
        with tab1:
            st.subheader("Did your salesperson lie to you?")
            st.write("Enter the exact numbers on your contract. We will run it against your *actual* historical meter data.")
            
            c1, c2, c3, c4 = st.columns(4)
            qc_size = c1.number_input("Quoted Solar (kW)", value=6.6)
            qc_batt = c2.number_input("Quoted Battery (kWh)", value=0.0)
            qc_cost = c3.number_input("Total Price ($)", value=6500)
            qc_payback = c4.number_input("Promised Payback (Years)", value=3.5)
            
            if st.button("Run The Math", type="primary"):
                with st.spinner("Crunching physics..."):
                    sim_res = run_simulation(df, qc_size, qc_batt, export_limit, region_yield)
                    econ = calc_residential_economics(sim_res, qc_cost)
                    real_payback = econ['Payback_Years']
                    
                    # --- SECURE DATA TO SESSION STATE ---
                    st.session_state['qc_data'] = {
                        'real_payback': real_payback,
                        'econ': econ,
                        'qc_cost': qc_cost,
                        'qc_size': qc_size
                    }
                    
                    st.divider()
                    st.markdown("### The Verdict")
                    if abs(real_payback - qc_payback) <= 1.0:
                        st.success(f"✅ **PASS (HONEST QUOTE):** The math checks out. They promised {qc_payback} years, and physics dictates {real_payback:.1f} years.")
                    elif real_payback > qc_payback + 1.0:
                        st.error(f"❌ **FAIL (OVER-PROMISED):** They are lying to you. They promised {qc_payback} years, but your real-world usage dictates {real_payback:.1f} years. Do not sign this.")
                    else:
                        st.warning(f"⚠️ **WARNING (UNDER-PROMISED):** They quoted {qc_payback} years, but you'll actually pay it off in {real_payback:.1f} years. They used generic assumptions, but the deal is heavily in your favor.")
                    
                    colA, colB = st.columns(2)
                    colA.metric("Calculated Annual Savings", f"${econ['Annual_Savings']:,.2f}")
                    colB.metric("Grid Independence", f"{econ['Independence']:.1f}%")

        # --- TAB 2: ROOF OPTIMIZER ---
        with tab2:
            st.subheader("The Orientation Delta Engine")
            st.write("Standard quotes dump 100% of panels on the North roof. Let's see if aligning panels with your peak usage habits generates more cash.")
            
            ro_size = st.number_input("System Size for Test (kW)", value=6.6, key="ro_size")
            ro_direction = st.selectbox("Select Alternative Layout (Sim B)", ["West (Afternoon Heavy)", "East (Morning Heavy)", "Split (East/West)"])
            
            if st.button("Run Optimizer vs Standard North"):
                sim_a = run_directional_simulation(df, ro_size, 0, export_limit, region_yield, direction="North")
                econ_a = calc_residential_economics(sim_a, 6000) 
                
                sim_b = run_directional_simulation(df, ro_size, 0, export_limit, region_yield, direction=ro_direction)
                econ_b = calc_residential_economics(sim_b, 6000)
                
                delta = econ_b['Annual_Savings'] - econ_a['Annual_Savings']
                
                if delta > 0:
                     st.success(f"🔥 **OPTIMIZATION FOUND:** A {ro_direction} layout generates an extra **${delta:,.2f} per year** in pure cash compared to a standard North setup.")
                else:
                     st.info(f"🧭 **STAY NORTH:** A {ro_direction} layout loses **${abs(delta):,.2f} per year** compared to standard North. Keep them pointing North.")
                
                st.caption("*Legal Disclaimer: This simulation assumes standard roof viability, unshaded access, and suitable pitch. Always consult a structural engineer before installation.*")

        # --- TAB 3: PDF EXPORT ---
        with tab3:
            st.subheader("Generate Ammunition")
            st.write("Generate a hostile PDF audit to use as leverage against your salesperson.")
            
            if st.session_state['qc_data'] is None:
                st.warning("⚠️ Please run 'The Bullshit Detector' in Tab 1 first to calculate your metrics.")
            else:
                if st.button("Generate Audit PDF"):
                    data = st.session_state['qc_data']
                    stats = {
                        "System": "Quoted System Audit", 
                        "Cost": data['qc_cost'], 
                        "Payback (Yrs)": data['real_payback'], 
                        "Annual Savings": data['econ'].get('Annual_Savings', 0),
                        "Lifetime NPV": data['econ'].get('NPV', 0)
                    }
                    
                    with st.spinner("AI is writing your report..."):
                        try:
                            ai_text = generate_ai_commentary(stats, "Residential (Home)")
                            pdf_data = create_pdf(stats, "Residential (Home)", f"{data['qc_size']}kW Audit", ai_text)
                            
                            st.download_button(
                                label="⬇️ Download Leverage Document", 
                                data=pdf_data, 
                                file_name="Truth_Audit.pdf", 
                                mime="application/pdf"
                            )
                        except Exception as e:
                            st.error(f"Failed to generate Audit PDF: {str(e)}")
