import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

# Custom CSS for styling
st.markdown(
    """
    <style>
    html, body, [class*="css"] {
        font-family: 'Arial', sans-serif;
        color: #8068FF;
    }

    h1, h3 {
        color: #8068FF;
    }

    button {
        border: 2px solid #4A4A86;
        color: #4A4A86;
        background-color: transparent;
        border-radius: 5px;
        padding: 10px 15px;
        font-size: 16px;
        font-weight: bold;
        transition: background-color 0.3s, color 0.3s;
    }
    button:hover {
        background-color: #8068FF;
        color: white;
    }

    input, select, textarea {
        border: 2px solid #4A4A86;
        border-radius: 5px;
        padding: 8px;
        font-size: 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Multiselect for platform selection
selected_platforms = st.multiselect(
    "Select Platform(s) to Adjust Budgets For",
    options=["Meta Ads", "Google Ads"],
)

# Function to calculate remaining days in the current month
def calculate_remaining_days(selected_end_date):
    last_day_of_month = (selected_end_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    remaining_days = (last_day_of_month - selected_end_date).days + 1
    return remaining_days

# Meta Ads Functionality
if "Meta Ads" in selected_platforms:
    st.subheader("Meta Ads Budget and Spend Viewer")

    # Inputs
    access_token = st.text_input("Meta Ads Access Token", type="password")
    ad_account_id = st.text_input("Ad Account ID")
    total_monthly_budget = st.number_input("Total Monthly Budget Allocated ($)", min_value=0.0, step=1.0)

    # Add padding percentage dropdown
    padding_option = st.selectbox(
        "Select Padding Percentage",
        ["1%", "2%", "3%", "4%", "5%", "Custom"],
        index=4  # Default to 5%
    )

    # Handle custom padding input
    if padding_option == "Custom":
        custom_padding = st.number_input(
            "Enter Custom Padding (%)", min_value=0.0, max_value=100.0, step=1.0
        )
        padding_percent = 1 - (custom_padding / 100)
    else:
        padding_percent = 1 - (int(padding_option.strip("%")) / 100)

    # Date range input
    date_range = st.date_input("Date Range", [datetime.now().replace(day=1), datetime.now()])
    if len(date_range) == 2:
        start_date = date_range[0].strftime("%Y-%m-%d")
        end_date = date_range[1].strftime("%Y-%m-%d")
        remaining_days = calculate_remaining_days(date_range[1])

    # Fetch campaigns with budgets
    def fetch_campaigns_with_budgets(access_token, ad_account_id):
        url = f"https://graph.facebook.com/v15.0/act_{ad_account_id}/campaigns"
        params = {
            "fields": "id,name,daily_budget",
            "effective_status": '["ACTIVE"]',
            "access_token": access_token,
        }
        response = requests.get(url, params=params)
        return response.json()

    # Fetch ad sets with budgets
    def fetch_adsets_with_budgets(access_token, campaign_id):
        url = f"https://graph.facebook.com/v15.0/{campaign_id}/adsets"
        params = {
            "fields": "id,name,daily_budget",
            "effective_status": '["ACTIVE"]',
            "access_token": access_token,
        }
        response = requests.get(url, params=params)
        return response.json()

    # Fetch spend data
    def fetch_spend(access_token, entity_id, start_date, end_date):
        url = f"https://graph.facebook.com/v15.0/{entity_id}/insights"
        params = {
            "fields": "spend",
            "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
            "access_token": access_token,
        }
        response = requests.get(url, params=params)
        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            return float(data["data"][0]["spend"])
        return 0.0

    # Process campaigns and ad sets
    def process_campaign_and_adset_budgets(access_token, ad_account_id, start_date, end_date):
        campaigns_response = fetch_campaigns_with_budgets(access_token, ad_account_id)
        if "error" in campaigns_response:
            return None, campaigns_response["error"]

        all_data = []

        for campaign in campaigns_response.get("data", []):
            # Check if the campaign has a budget set
            campaign_budget = campaign.get("daily_budget")
            if campaign_budget:
                # Process the campaign
                campaign_budget = int(campaign_budget) / 100
                spend = fetch_spend(access_token, campaign["id"], start_date, end_date)
                all_data.append({
                    "Name": campaign["name"],
                    "Daily Budget ($)": campaign_budget,
                    "Spend ($)": spend,
                    "Daily Spend %": 0.0,
                    "New Daily %": 0.0,
                    "New Daily Budget ($)": 0.0,
                })
            else:
                # Process ad sets if the campaign does not have a budget
                adsets_response = fetch_adsets_with_budgets(access_token, campaign["id"])
                for adset in adsets_response.get("data", []):
                    adset_budget = adset.get("daily_budget")
                    if adset_budget:
                        adset_budget = int(adset_budget) / 100
                        spend = fetch_spend(access_token, adset["id"], start_date, end_date)
                        all_data.append({
                            "Name": adset["name"],
                            "Daily Budget ($)": adset_budget,
                            "Spend ($)": spend,
                            "Daily Spend %": 0.0,
                            "New Daily %": 0.0,
                            "New Daily Budget ($)": 0.0,
                        })

        # Calculate percentages
        total_daily_budget = sum(row["Daily Budget ($)"] for row in all_data)
        for row in all_data:
            row["Daily Spend %"] = round((row["Daily Budget ($)"] / total_daily_budget) * 100, 2) if total_daily_budget > 0 else 0
            row["New Daily %"] = row["Daily Spend %"]

        return all_data, None

    # Fetch and process data
    if st.button("Fetch Meta Ads Data"):
        all_data, error = process_campaign_and_adset_budgets(access_token, ad_account_id, start_date, end_date)
        if error:
            st.error(f"Error fetching data: {error}")
        else:
            st.session_state["campaign_data"] = pd.DataFrame(all_data)
            st.session_state["total_spend"] = st.session_state["campaign_data"]["Spend ($)"].sum()
            st.session_state["total_budget_remaining"] = max(total_monthly_budget - st.session_state["total_spend"], 0) * padding_percent
            st.session_state["remaining_days"] = remaining_days

    if "campaign_data" in st.session_state:
        campaign_data = st.session_state["campaign_data"]
        total_spend = st.session_state["total_spend"]
        total_budget_remaining = st.session_state["total_budget_remaining"]
        remaining_days = st.session_state["remaining_days"]

        # Display in AgGrid
        gb = GridOptionsBuilder.from_dataframe(campaign_data)
        gb.configure_column("New Daily %", editable=True, cellStyle=JsCode("""
            function(params) {
                if (params.colDef.field === "New Daily %") {
                    return {'backgroundColor': '#8068FF', 'color': 'white', 'fontWeight': 'bold', 'textAlign': 'center'};
                }
                return {};
            }
        """))
        grid_options = gb.build()

        grid_response = AgGrid(
            campaign_data,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.VALUE_CHANGED,
            allow_unsafe_jscode=True,
            fit_columns_on_grid_load=True,
        )

        if st.button("Calculate New Daily Budgets"):
            updated_df = pd.DataFrame(grid_response["data"])
            new_daily_percent_sum = updated_df["New Daily %"].sum()

            if new_daily_percent_sum > 100:
                st.error(
                    f"The daily % is greater than 100% (current daily % set at {new_daily_percent_sum:.2f}%). "
                    "Please recalculate and resubmit."
                )
            else:
                updated_df["New Daily Budget ($)"] = updated_df["New Daily %"].apply(
                    lambda x: round((x / 100 * total_budget_remaining) / remaining_days, 2)
                )
                st.session_state["campaign_data"] = updated_df
                st.write("### Updated Campaigns Spend Data")
                st.dataframe(updated_df)

        # Display Summary Metrics
        st.write("### Summary")
        st.write(f"**Total Spend for Selected Period:** ${total_spend:.2f}")
        st.write(f"**Total Budget Remaining ({int(padding_percent * 100)}%):** ${total_budget_remaining:.2f}")
        st.write(f"**Total Days Remaining in Month:** {remaining_days} days")

# Google Ads Placeholder
if "Google Ads" in selected_platforms:
    st.subheader("Google Ads Budget and Spend Viewer")
    st.info("Platform Coming Soon")
