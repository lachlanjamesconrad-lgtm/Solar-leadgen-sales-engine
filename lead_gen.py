import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from supabase import create_client, Client

# -----------------------------------------------------------------------------
# 1. CONFIGURATION & UI SETUP
# -----------------------------------------------------------------------------
st.set_page_config(page_title="My Solar Plan | Free Simulator", page_icon="☀️", layout="wide")

st.title("☀️ Free Solar & Battery Simulator")
st.markdown("Discover how much you could save with solar. No math required.")

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

# Input 3: Time Home
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
st.sidebar.header("2. Build your System & Grid Rules")
sys_size = st.sidebar.slider("Solar System Size (kW)", min_value=3.0, max_value=15.0, value=6.6, step=0.1)
batt_size = st.sidebar.slider("Battery Size (kWh)", min_value=0.0, max_value=20.0, value=0.0, step=1.0)
export_limit = st.sidebar.selectbox(
    "Grid Export Limit (Energex Rule)", 
    ["No Limit (Old Math)", "5.0 kW (Standard Phase)", "1.5 kW (Dynamic Limit)", "0.0 kW (Zero Export)"]
)

export_cap_kw = float(export_limit.split(" ")) if "No Limit" not in export_limit else float('inf')

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
# 4. VISUALIZATION ENGINE (THE BULLSHIT DETECTOR)
# -----------------------------------------------------------------------------
st.subheader("📊 The Bullshit Detector: Your True Energy Profile")
st.markdown("Watch how export limits throttle generic quotes, and how batteries protect you during the 4 PM evening peak.")

fig = go.Figure()

fig.add_trace(go.Bar(x=df['Hour'], y=df['Grid Import (kWh)'], name='Grid Import (Buying $$)', marker_color='red', opacity=0.8))
fig.add_trace(go.Bar(x=df['Hour'], y=-df['Grid Export (kWh)'], name='Grid Export (Selling ¢¢)', marker_color='green', opacity=0.8))
fig.add_trace(go.Scatter(x=df['Hour'], y=df['Solar Generation (kWh)'], mode='lines', name='Raw Solar Output', line=dict(color='orange', width=2, dash='dot')))

if batt_size > 0:
    fig.add_trace(go.Scatter(x=df['Hour'], y=df['Battery SoC (kWh)'], mode='lines', name='Battery Charge Level', line=dict(color='blue', width=3), yaxis='y2'))

fig.update_layout(
    barmode='relative',
    xaxis_title="Time of Day",
    yaxis_title="Energy (kWh)",
    yaxis2=dict(title="Battery Charge (kWh)", overlaying='y', side='right', range=[0, max(20, batt_size)]),
    hovermode="x unified",
    margin=dict(l=0, r=0, t=30, b=0),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)
st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------------------
# 5. THE DATA CAPTURE & UPSELL GATE
# -----------------------------------------------------------------------------
st.divider()

if not st.session_state.lead_captured:
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 🔒 Unlock Your Financial Truth")
        st.write("Salesmen show you a perfect bell curve. We show you the mathematical reality. To see your true **Payback Period** and **Year 1 Cash Savings**, unlock your free summary.")
        
        with st.form("lead_capture_form"):
            email = st.text_input("Email Address", placeholder="you@example.com")
            consent = st.checkbox("I agree to the Privacy Policy and consent to receiving my solar simulation. This is a mathematical model, not financial advice.")
            
            submit = st.form_submit_button("Reveal My ROI 🚀")
            
            if submit:
                if email and consent:
                    try:
                        # Database connection to Supabase
                        url: str = st.secrets["SUPABASE_URL"]
                        key: str = st.secrets["SUPABASE_KEY"]
                        supabase: Client = create_client(url, key)

                        # Package the lead data based on what they were testing
                        lead_data = {
                            "email": email,
                            "consent_given": consent,
                            "system_size_kw": sys_size,
                            "battery_size_kwh": batt_size,
                            "export_limit_kw": export_cap_kw if export_cap_kw != float('inf') else 999 
                        }

                        # Fire it into the database
                        response = supabase.table('leads').insert(lead_data).execute()

                        # Change the state to reveal the upsell
                        st.session_state.lead_captured = True
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"System Error routing data: {str(e)}")
                else:
                    st.warning("Please provide a valid email and accept the Privacy Policy to continue.")

    with col2:
        st.info("💡 **Why do we need your email?**\n\nSolar is a financial asset, not a roof ornament. We send you a detailed, easy-to-read report that prevents you from getting ripped off by bad quotes. No spam, just the math.")

else:
    # THE UPSELL STATE (Visible only after email capture)
    st.success("✅ Success! Your baseline simulation report is being generated and sent to your inbox.")
    
    st.markdown("---")
    st.markdown("## 🚨 Do you already have quotes from installers?")
    st.warning("**Don't sign a $15k contract based on generic math. Pay $149 and let an engineer audit the physics.**")
    st.write("The simulation above uses averages. Our **Truth Audit** ingests your exact Energex smart meter data (NEM12) and your specific installer quotes to calculate precise 10-year Net Present Value, battery opportunity costs, and true payback periods.")
    
    col3, col4 = st.columns(2)
    with col3:
        # REPLACE THIS URL WITH YOUR STRIPE PAYMENT LINK LATER
        st.link_button("Buy Independent Audit ($149) 🔍", "https://buy.stripe.com/test_link_placeholder", type="primary")
    with col4:
        st.write("*(Redirects to Stripe. You will upload your top 3 quotes and NEM12 CSV on the secure form following payment.)*")
