import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import StringIO
import numpy_financial as npf 

# -----------------------------------------------------------------------------
# 1. CORE CONFIG & CONSTANTS (PRESERVED)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="SunScore Analytics | Pro Sales Simulator", page_icon="📈", layout="wide")

YIELD_MAP = {
    "Brisbane (North)": 4.2,
    "Brisbane (South)": 4.1,
    "Gold Coast": 4.0,
    "Sunshine Coast": 4.3,
    "Ipswich / West": 4.4
}

RETAIL_RATE_RES = 0.34    
FEED_IN_RES = 0.05        
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
        try: content = file.getvalue().decode('utf-8')
        except UnicodeDecodeError: content = file.getvalue().decode('latin-1')
        
        if "RateTypeDescription" in content or "ProfileReadValue" in content:
            try:
                df = pd.read_csv(StringIO(content))
                df.columns = df.columns.str.strip()
                desc_col = next((c for c in df.columns if c in ['RateTypeDescription', 'Rate Type', 'RegisterCode']), None)
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
            except: pass 

        df = pd.read_csv(StringIO(content))
        col_map = {'Usage': 'Usage_kWh', 'Consumption': 'Usage_kWh', 'Quantity': 'Usage_kWh', 'Start Time': 'Time', 'StartDate': 'Time', 'Interval End': 'Time', 'Date': 'Time'}
        df.rename(columns=lambda x: col_map.get(x, x), inplace=True)
        if 'Time' in df.columns and 'Usage_kWh' in df.columns:
            df['Time'] = pd.to_datetime(df['Time'], dayfirst=True, errors='coerce')
            df = df.dropna(subset=['Time']).set_index('Time').sort_index()
            df['Usage_kWh'] = pd.to_numeric(df['Usage_kWh'], errors='coerce').fillna(0)
            return df[['Usage_kWh']].resample('h').sum().fillna(0)

        # --- NEW PARSING CAPABILITIES FALLBACK A (Silent failure handler) ---
        try:
            df2 = pd.read_csv(StringIO(content))
            # Catch format 2 and other broad column names
            broad_map = {'Date/Time': 'Time', 'kWh': 'Usage_kWh'}
            df2.rename(columns=lambda x: broad_map.get(x, x), inplace=True)
            if 'Time' in df2.columns and 'Usage_kWh' in df2.columns:
                # Catch format 3 (US formats & ambiguous dates)
                df2['Time'] = pd.to_datetime(df2['Time'], format="mixed", dayfirst=True, errors='coerce')
                # If everything failed to parse (NaT), try dayfirst=False explicitly
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
    
    sim['Solar_Gen_kWh'] = np.tile(hourly_gen, days + 1)[:len(sim)]
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
            
    sim['Grid_Export_kWh'] = grid_export; sim['Grid_Import_kWh'] = grid_import
    return sim

# -----------------------------------------------------------------------------
# 3. FINANCIAL ENGINES (PRESERVED)
# -----------------------------------------------------------------------------
def calculate_dcf(annual_savings, cost, years=20, financing_setup=None):
    cash_flows = [0] if financing_setup else [-cost]
    loan_payment = 0
    if financing_setup:
        r = financing_setup['rate'] / 12
        n = financing_setup['term'] * 12
        if r > 0:
             loan_payment = (cost * (r * (1 + r)**n) / ((1 + r)**n - 1)) * 12
    
    for i in range(1, years + 1):
        current_year_net = annual_savings * ((1 + RES_INFLATION) ** (i-1))
        if financing_setup and i <= financing_setup['term']: current_year_net -= loan_payment
        cash_flows.append(current_year_net)
    
    npv = npf.npv(DISCOUNT_RATE, cash_flows)
    irr = npf.irr(cash_flows) if cash_flows else 0
    unlevered_npv = npf.npv(DISCOUNT_RATE, [-cost] + [annual_savings * ((1 + RES_INFLATION) ** (i-1)) for i in range(1, years+1)])
    return npv, irr, unlevered_npv + cost, cash_flows

def calc_residential_economics(sim_df, system_cost, finance_config=None):
    if sim_df.empty: return {}
    import_cost_orig = sim_df['Usage_kWh'].sum() * RETAIL_RATE_RES
    import_cost_new = sim_df['Grid_Import_kWh'].sum() * RETAIL_RATE_RES
    export_credit = sim_df['Grid_Export_kWh'].sum() * FEED_IN_RES
    
    savings = import_cost_orig - (import_cost_new - export_credit)
    payback = system_cost / savings if savings > 0 else 99
    npv, irr, val_uplift, cashflows = calculate_dcf(savings, system_cost, years=20, financing_setup=finance_config)
    return {"Annual_Savings": savings, "Payback_Years": payback, "NPV": npv, "Valuation_Uplift": val_uplift, "Cashflows": cashflows}

# -----------------------------------------------------------------------------
# 4. B2B SALES UI (KITCHEN TABLE CLOSER)
# -----------------------------------------------------------------------------
st.title("SunScore Analytics | Investment Proposal")
st.markdown("Professional Tier Financial Modeling for Residential Assets.")

with st.sidebar:
    st.header("Client Setup")
    selected_region = st.selectbox("📍 Region", list(YIELD_MAP.keys()))
    region_yield = YIELD_MAP[selected_region]
    
    st.markdown("---")
    st.header("Financing Profile")
    is_financed = st.checkbox("Apply Green Loan / Finance?")
    finance_config = None
    if is_financed:
        rate = st.number_input("Interest Rate (%)", 0.0, 15.0, 6.9, 0.1)
        term = st.slider("Loan Term (Years)", 3, 10, 5)
        finance_config = {'rate': rate/100, 'term': term}
        
    uploaded_file = st.file_uploader("Upload Client Interval Data", type=['csv'])

if uploaded_file is not None:
    df = load_and_clean_data(uploaded_file)
    if not df.empty:
        tab1, tab2 = st.tabs(["💎 Long-Term Value Creation", "⚖️ Competitor Financial Comparison"])
        
        # --- TAB 1: THE PREMIUM PROPOSAL ---
        with tab1:
            st.subheader("Your Custom Solar Asset Valuation")
            st.write("We model solar not as an expense, but as an appreciating asset added to your property.")
            
            c1, c2, c3 = st.columns(3)
            prop_size = c1.number_input("Proposed Solar (kW)", value=10.3)
            prop_batt = c2.number_input("Proposed Battery (kWh)", value=13.5)
            prop_cost = c3.number_input("System Investment ($)", value=18500)
            prop_export = 5.0 # Premium dynamic export assumed
            
            sim_premium = run_simulation(df, prop_size, prop_batt, prop_export, region_yield)
            econ_premium = calc_residential_economics(sim_premium, prop_cost, finance_config)
            
            st.divider()
            
            # The Valuation Focus
            vc1, vc2, vc3 = st.columns(3)
            vc1.metric("Year 1 Cash Savings", f"${econ_premium['Annual_Savings']:,.0f}")
            vc2.metric("20-Year Net Wealth Created", f"${econ_premium['NPV']:,.0f}")
            vc3.metric("Property Valuation Uplift", f"${econ_premium['Valuation_Uplift']:,.0f}")
            
            st.markdown("### Cumulative Cashflow Pipeline")
            st.caption("Visualizing the transition from investment recovery to pure profit generation.")
            
            
            # Plotly Cumulative Cashflows
            cf_premium = np.cumsum(econ_premium['Cashflows'])
            years = np.arange(len(cf_premium))
            fig_cf = go.Figure()
            fig_cf.add_trace(go.Scatter(x=years, y=cf_premium, mode='lines+markers', name='Wealth Trajectory', line=dict(color='#00b4d8', width=4)))
            fig_cf.add_shape(type="line", x0=0, y0=0, x1=20, y1=0, line=dict(color="red", width=2, dash="dash"))
            fig_cf.update_layout(xaxis_title="Years Post-Installation", yaxis_title="Cumulative Net Benefit ($)", hovermode="x unified")
            st.plotly_chart(fig_cf, use_container_width=True)

        # --- TAB 2: COMPETITOR COMPARISON (THE CLOSER) ---
        with tab2:
            st.subheader("The True Cost of 'Cheap' Solar")
            st.write("Compare our premium architecture against standard, restrictive quotes side-by-side.")
            
            col_a, col_b = st.columns(2)
            
            with col_a:
                st.markdown("### 🏆 SunScore Premium System")
                st.write("High efficiency, battery-ready, dynamic export allowance.")
                prem_cost = st.number_input("Investment ($)", value=prop_cost, key="p_cost")
                # Using the premium sim run in Tab 1
                
            with col_b:
                st.markdown("### ⚠️ Competitor Quote")
                st.write("Standard string inverter, hard STNW1170 zero-export limits.")
                comp_size = st.number_input("Quoted Solar (kW)", value=6.6, key="c_size")
                comp_batt = st.number_input("Quoted Battery (kWh)", value=0.0, key="c_batt")
                comp_cost = st.number_input("Quoted Price ($)", value=5500, key="c_cost")
                comp_export = st.selectbox("Competitor Export Limit", [0.0, 1.5, 5.0], index=0, help="Cheap inverters often get locked to 0 export.")
                
            if st.button("Run 10-Year Financial Comparison", type="primary"):
                sim_comp = run_simulation(df, comp_size, comp_batt, comp_export, region_yield)
                econ_comp = calc_residential_economics(sim_comp, comp_cost, finance_config)
                
                # Update Premium just in case cost was changed in Tab 2
                econ_premium = calc_residential_economics(sim_premium, prem_cost, finance_config)
                
                st.divider()
                
                # The Gap Calculation
                prem_10yr = sum(econ_premium['Cashflows'][1:11]) - (prem_cost if not finance_config else sum([prem_cost*(finance_config['rate']/12*(1+finance_config['rate']/12)**(finance_config['term']*12))/((1+finance_config['rate']/12)**(finance_config['term']*12)-1)*12 for _ in range(finance_config['term'])]))
                comp_10yr = sum(econ_comp['Cashflows'][1:11]) - (comp_cost if not finance_config else sum([comp_cost*(finance_config['rate']/12*(1+finance_config['rate']/12)**(finance_config['term']*12))/((1+finance_config['rate']/12)**(finance_config['term']*12)-1)*12 for _ in range(finance_config['term'])]))
                
                # Fix for simplified 10yr cash flow sum for display
                prem_cf_cum = np.cumsum(econ_premium['Cashflows'])
                comp_cf_cum = np.cumsum(econ_comp['Cashflows'])
                
                gap_10yr = prem_cf_cum[10] - comp_cf_cum[10]
                
                st.markdown(f"### The 10-Year Opportunity Cost: **${gap_10yr:,.0f}**")
                if gap_10yr > 0:
                    st.info(f"Choosing the cheaper competitor quote actually **costs the client ${gap_10yr:,.0f}** in lost savings and export revenue over the next decade due to inferior hardware and grid throttling.")
                
                
                
                fig_comp = go.Figure()
                fig_comp.add_trace(go.Scatter(x=np.arange(11), y=prem_cf_cum[:11], mode='lines+markers', name='SunScore Premium', line=dict(color='#00b4d8', width=4)))
                fig_comp.add_trace(go.Scatter(x=np.arange(11), y=comp_cf_cum[:11], mode='lines+markers', name='Competitor Quote', line=dict(color='#ff4d4d', width=4, dash='dot')))
                fig_comp.add_shape(type="line", x0=0, y0=0, x1=10, y1=0, line=dict(color="gray", width=1))
                
                fig_comp.update_layout(title="Cumulative Financial Position (10 Years)", xaxis_title="Years", yaxis_title="Net Position ($)", hovermode="x unified")
                st.plotly_chart(fig_comp, use_container_width=True)