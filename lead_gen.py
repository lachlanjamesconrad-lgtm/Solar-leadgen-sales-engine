import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from supabase import create_client, Client

if "payment" in st.query_params and st.query_params["payment"] == "success":
    st.success("🎉 Payment Successful! Your Engineering Audit is confirmed.")
    st.markdown("### Next Steps:")
    st.write("We have received your $149 payment. To get started, please forward your Energex Smart Meter data and your solar quotes to **audits@sunscore.com.au**.")
    st.info("Haven't got your Energex data yet? Log into your electricity retailer portal and request your 'NEM12 Smart Meter Interval Data' CSV file.")
    
    # Stop the rest of the app from loading so they don't see the calculator
    st.stop()

# -----------------------------------------------------------------------------
# 1. CONFIGURATION & UI SETUP
# -----------------------------------------------------------------------------
st.set_page_config(page_title="My Solar Plan | Free Simulator", page_icon="☀️", layout="wide")

st.title("My Solar Plan")
st.subheader("☀️ Free Solar Simulator")
st.markdown("Discover your baseline solar potential. No math required.")

# Initialize session state for the email gate
if "lead_captured" not in st.session_state:
    st.session_state.lead_captured = False

# -----------------------------------------------------------------------------
# 2. SYNTHETIC LOAD PROFILE GENERATOR
# -----------------------------------------------------------------------------
st.sidebar.header("1. Tell us about your home")

# Input 1: Postcode 
postcode = st.sidebar.text_input("Postcode", value="4037")

# Input 2: Quarterly Bill
quarterly_bill = st.sidebar.slider("Average Quarterly Bill ($)", min_value=150, max_value=1500, value=450, step=50)

# Input 3: Time Home (Simplified for the free tier)
occupancy = st.sidebar.selectbox(
    "When is the house most occupied?",
    ["Mostly Evenings (Work away from home)", "Day & Night (WFH / Retired)", "Always Home (Large Family)"]
)

# Input 4: Big Appliances
appliances = st.sidebar.multiselect(
    "Select your heavy energy users:",
    ["Pool Pump", "Electric Vehicle (EV)", "Ducted Aircon"]
)

def generate_synthetic_load(bill, occupancy, appliances):
    """Heuristic engine to build a 24-hour kWh consumption curve."""
    daily_kwh = (bill / 90) / 0.30 
    
    hours = np.arange(24)
    base_load = np.ones(24) * (daily_kwh * 0.02) 
    
    if "Evenings" in occupancy:
        profile = np.array([0.5, 0.4, 0.4, 0.5, 0.8, 2.0, 3.0, 2.5, 1.0, 0.8, 0.8, 0.9, 1.0, 1.0, 1.2, 2.5, 4.0, 6.0, 7.0, 6.5, 5.0, 3.0, 1.5, 0.8])
    elif "WFH" in occupancy:
        profile = np.array([0.8, 0.8, 0.8, 0.8, 1.0, 1.5, 2.5, 3.0, 3.5, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.5, 5.0, 6.0, 5.5, 5.0, 4.0, 2.5, 1.5, 1.0])
    else:
        profile = np.array([1.0, 1.0, 1.0, 1.0, 1.5, 2.0, 3.5, 4.5, 4.0, 4.5, 4.5, 4.5, 4.5, 4.5, 4.5, 5.0, 6.0, 7.0, 7.5, 7.0, 5.5, 3.5, 2.0, 1.5])
    
    profile = (profile / np.sum(profile)) * daily_kwh
    
    if "Pool Pump" in appliances:
        profile[10:14] += 1.5 
    if "Electric Vehicle (EV)" in appliances:
        profile[22:24] += 3.0
        profile[0:2] += 3.0
    if "Ducted Aircon" in appliances:
        profile[15:20] += 2.0
        
    return base_load + profile

synthetic_load = generate_synthetic_load(quarterly_bill, occupancy, appliances)

# -----------------------------------------------------------------------------
# 3. ADVANCED SYSTEM SIZING & PHYSICS ENGINE
# -----------------------------------------------------------------------------
st.sidebar.header("2. Build your System")
sys_size = st.sidebar.slider("Solar System Size (kW)", min_value=3.0, max_value=15.0, value=6.6, step=0.1)

# STRATEGY PIVOT: Hardcode limits so the graph shows the 'Salesman Dream'
batt_size = 0.0 
export_cap_kw = float('inf')  

def generate_solar_curve(size_kw):
    hours = np.arange(24)
    gen = size_kw * 0.75 * np.exp(-0.5 * ((hours - 13) / 2.5)**2) 
    gen[0:6] = 0
    gen[19:24] = 0
    return gen

solar_gen = generate_solar_curve(sys_size)

def calculate_energy_flow(consumption, generation, battery_capacity, export_cap):
    batt_soc = np.zeros(24)
    grid_import = np.zeros(24)
    grid_export = np.zeros(24)
    current_charge = 0.0

    for i in range(24):
        net_energy = generation[i] - consumption[i]

        if net_energy > 0: 
            charge_capacity = battery_capacity - current_charge
            to_battery = min(net_energy, charge_capacity)
            current_charge += to_battery

            to_grid = net_energy - to_battery
            grid_export[i] = min(to_grid, export_cap)

        else: 
            draw_needed = abs(net_energy)
            from_battery = min(draw_needed, current_charge)
            current_charge -= from_battery

            grid_import[i] = draw_needed - from_battery

        batt_soc[i] = current_charge

    return grid_import, grid_export, batt_soc

grid_import, grid_export, batt_soc = calculate_energy_flow(synthetic_load, solar_gen, batt_size, export_cap_kw)

df = pd.DataFrame({
    'Hour': [f"{h:02d}:00" for h in range(24)],
    'Consumption (kWh)': synthetic_load,
    'Solar Generation (kWh)': solar_gen,
    'Grid Import (kWh)': grid_import,
    'Grid Export (kWh)': grid_export,
    'Battery SoC (kWh)': batt_soc
})

# -----------------------------------------------------------------------------
# 4. VISUALIZATION ENGINE (THE SETUP)
# -----------------------------------------------------------------------------
st.subheader("📊 Your Baseline Energy Profile")
st.markdown("Salesmen use this exact 'perfect' curve to sell you systems. Notice the massive green export zone.")

fig = go.Figure()

fig.add_trace(go.Bar(x=df['Hour'], y=df['Grid Import (kWh)'], name='Grid Import (Buying $$)', marker_color='red', opacity=0.8))
fig.add_trace(go.Bar(x=df['Hour'], y=-df['Grid Export (kWh)'], name='Assumed Export (Selling ¢¢)', marker_color='green', opacity=0.8))
fig.add_trace(go.Scatter(x=df['Hour'], y=df['Solar Generation (kWh)'], mode='lines', name='Raw Solar Output', line=dict(color='orange', width=2, dash='dot')))

fig.update_layout(
    barmode='relative',
    xaxis_title="Time of Day",
    yaxis_title="Energy (kWh)",
    hovermode="x unified",
    margin=dict(l=0, r=0, t=30, b=0),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)
st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------------------
# 5. THE DATA CAPTURE & UPSELL GATE (THE PUNCHLINE)
# -----------------------------------------------------------------------------
st.divider()

if not st.session_state.lead_captured:
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 🔒 The 'Perfect Scenario' Trap")
        st.write("The graph above assumes the grid can accept 100% of your excess power. **In reality, Energex places strict dynamic limits on exactly how much you can sell back.** Enter your email below to see your baseline payback period, and discover if you are at risk of grid throttling.")
        
        with st.form("lead_capture_form"):
            email = st.text_input("Email Address", placeholder="you@example.com")
            consent = st.checkbox("I agree to the Privacy Policy. This is a mathematical simulation, not financial advice.")
            
            submit = st.form_submit_button("Reveal My ROI 🚀")
            
            if submit:
                if email and consent:
                    try:
                        # Database connection to Supabase
                        url: str = st.secrets["SUPABASE_URL"]
                        key: str = st.secrets["SUPABASE_KEY"]
                        supabase: Client = create_client(url, key)

                        lead_data = {
                            "email": email,
                            "consent_given": consent,
                            "system_size_kw": sys_size,
                            "battery_size_kwh": batt_size,
                            "export_limit_kw": export_cap_kw if export_cap_kw != float('inf') else 999 
                        }

                        response = supabase.table('leads').insert(lead_data).execute()
                        st.session_state.lead_captured = True
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"System Error routing data: {str(e)}")
                else:
                    st.warning("Please provide a valid email and accept the Privacy Policy to continue.")

    with col2:
        st.info("💡 **Why do we need your email?**\n\nSolar is a financial asset, not a roof ornament. We send you a detailed, easy-to-read reality check that prevents you from getting ripped off by bad quotes. No spam, just the math.")

else:
    # THE UPSELL STATE
    st.success("✅ Success! Your baseline simulation report is being generated and sent to your inbox.")
    
    st.markdown("---")
    st.markdown("## 🚨 Do you already have quotes from installers?")
    st.warning("**Don't sign a $15k contract based on their 'perfect' spreadsheets. Pay $149 and let an independent engineer audit the physics.**")
    st.write("The simulation above uses averages. Our **Truth Audit** ingests your exact Energex smart meter data (NEM12) and your specific installer quotes to calculate precise 10-year Net Present Value, custom battery modeling, and real-world grid throttling risks.")
    
    col3, col4 = st.columns(2)
    with col3:
        st.link_button("Buy Independent Audit ($149) 🔍", "https://buy.stripe.com/", type="primary")
    with col4:
        st.write("*(Redirects to secure checkout. You will upload your top 3 quotes and NEM12 CSV on the secure form following payment.)*")
