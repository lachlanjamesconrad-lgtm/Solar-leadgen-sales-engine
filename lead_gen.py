import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# -----------------------------------------------------------------------------
# 1. CONFIGURATION & UI SETUP
# -----------------------------------------------------------------------------
st.set_page_config(page_title="My Solar Plan | Free Simulator", page_icon="☀️", layout="wide")

st.title("☀️ Free Solar & Battery Simulator")
st.markdown("Discover how much you could save with solar. No math required.")

# -----------------------------------------------------------------------------
# 2. SYNTHETIC LOAD PROFILE GENERATOR
# -----------------------------------------------------------------------------
st.sidebar.header("1. Tell us about your home")

# Input 1: Postcode (Defaulted to a standard Brisbane baseline)
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
    # Rough estimate: $0.30/kWh average tariff. Bill / 90 days = Daily Spend.
    daily_kwh = (bill / 90) / 0.30 
    
    hours = np.arange(24)
    base_load = np.ones(24) * (daily_kwh * 0.02) # Base standby power
    
    # Apply occupancy curves
    if "Evenings" in occupancy:
        profile = np.array([0.5, 0.4, 0.4, 0.5, 0.8, 2.0, 3.0, 2.5, 1.0, 0.8, 0.8, 0.9, 1.0, 1.0, 1.2, 2.5, 4.0, 6.0, 7.0, 6.5, 5.0, 3.0, 1.5, 0.8])
    elif "WFH" in occupancy:
        profile = np.array([0.8, 0.8, 0.8, 0.8, 1.0, 1.5, 2.5, 3.0, 3.5, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.5, 5.0, 6.0, 5.5, 5.0, 4.0, 2.5, 1.5, 1.0])
    else:
        profile = np.array([1.0, 1.0, 1.0, 1.0, 1.5, 2.0, 3.5, 4.5, 4.0, 4.5, 4.5, 4.5, 4.5, 4.5, 4.5, 5.0, 6.0, 7.0, 7.5, 7.0, 5.5, 3.5, 2.0, 1.5])
    
    # Normalize and scale to daily kWh
    profile = (profile / np.sum(profile)) * daily_kwh
    
    # Inject Appliance Spikes
    if "Pool Pump" in appliances:
        # Runs 10am to 2pm
        profile[10:14] += 1.5 
    if "Electric Vehicle (EV)" in appliances:
        # Assuming dumb charging at night 10pm to 2am
        profile[22:24] += 3.0
        profile[0:2] += 3.0
    if "Ducted Aircon" in appliances:
        # Afternoon/Evening peak
        profile[15:20] += 2.0
        
    return base_load + profile

synthetic_load = generate_synthetic_load(quarterly_bill, occupancy, appliances)

# -----------------------------------------------------------------------------
# 3. GAMIFIED SYSTEM SIZING
# -----------------------------------------------------------------------------
st.sidebar.header("2. Build your System")
sys_size = st.sidebar.slider("Solar System Size (kW)", min_value=3.0, max_value=15.0, value=6.6, step=0.1)
batt_size = st.sidebar.slider("Battery Size (kWh)", min_value=0.0, max_value=20.0, value=0.0, step=1.0)

def generate_solar_curve(size_kw):
    """Simplified bell curve for solar generation based on system size."""
    hours = np.arange(24)
    # Peak generation around 1pm (hour 13)
    gen = size_kw * 0.75 * np.exp(-0.5 * ((hours - 13) / 2.5)**2) 
    # Zero out night hours
    gen[0:6] = 0
    gen[19:24] = 0
    return gen

solar_gen = generate_solar_curve(sys_size)

# Calculate coverage (Basic visual estimation, excluding complex battery logic for Tier 1)
df = pd.DataFrame({
    'Hour': [f"{h:02d}:00" for h in range(24)],
    'Consumption (kWh)': synthetic_load,
    'Solar Generation (kWh)': solar_gen
})

# -----------------------------------------------------------------------------
# 4. VISUALIZATION ENGINE
# -----------------------------------------------------------------------------
st.subheader("📊 Your Estimated 24-Hour Energy Profile")


fig = go.Figure()
fig.add_trace(go.Scatter(x=df['Hour'], y=df['Consumption (kWh)'], mode='lines', name='Your Usage', line=dict(color='red', width=3)))
fig.add_trace(go.Scatter(x=df['Hour'], y=df['Solar Generation (kWh)'], fill='tozeroy', mode='none', name='Solar Output', fillcolor='rgba(255, 165, 0, 0.5)'))

fig.update_layout(
    xaxis_title="Time of Day",
    yaxis_title="Energy (kWh)",
    hovermode="x unified",
    margin=dict(l=0, r=0, t=30, b=0),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)
st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------------------
# 5. THE EMAIL GATE (LEAD CAPTURE)
# -----------------------------------------------------------------------------
st.divider()

col1, col2 = st.columns([1, 1])

with col1:
    st.markdown("### 🔒 Unlock Your Financial Truth")
    st.write("We've crunched the numbers based on your profile. To see your exact **Payback Period**, **ROI**, and **Year 1 Cash Savings**, unlock your free summary below.")
    
    with st.form("lead_capture_form"):
        email = st.text_input("Email Address", placeholder="you@example.com")
        submit = st.form_submit_button("Reveal My ROI 🚀")
        
        if submit and email:
            st.success("Success! Generating your personalized My Solar Plan... (Check your inbox)")
            # Here we would trigger the webhook/database insertion for the lead

with col2:
    st.info("💡 **Why do we need your email?**\n\nSolar is complex. We send you a detailed, easy-to-read report that prevents you from getting ripped off by bad quotes. No spam, just the math.")