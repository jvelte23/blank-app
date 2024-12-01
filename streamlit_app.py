import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
import requests
import time

# Function to calculate remaining days in the current month
def calculate_remaining_days(selected_end_date):
    last_day_of_month = (selected_end_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    remaining_days = (last_day_of_month - selected_end_date).days + 1
    return remaining_days

# Abstracted API Wrapper Class for Meta Ads
class MetaAPI:
    def __init__(self, access_token):
        self.access_token = access_token

    def _make_request(self, url, method="GET", params=None, data=None):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            response = requests.request(method, url, params=params, data=data, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    def fetch_campaigns_with_budgets(self, ad_account_id):
        url = f"https://graph.facebook.com/v15.0/act_{ad_account_id}/campaigns"
        params = {
            "fields": "id,name,daily_budget",
            "effective_status": '["ACTIVE"]',
        }
        return self._make_request(url, params=params)

    def fetch_spend(self, entity_id, start_date, end_date):
        url = f"https://graph.facebook.com/v15.0/{entity_id}/insights"
        params = {
            "fields": "spend",
            "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
        }
        data = self._make_request(url, params=params)
        if "data" in data and len(data["data"]) > 0:
            return float(data["data"][0]["spend"])
        return 0.0

    def update_budget(self, entity_id, new_budget):
        url = f"https://graph.facebook.com/v15.0/{entity_id}"
        data = {
            "daily_budget": int(new_budget * 100),  # Meta API expects budgets in cents
        }
        return self._make_request(url, method="POST", data=data)

# Streamlit UI
st.title("Campaign Budget Management for Meta Ads")

# Meta Ads Functionality
st.subheader("Meta Ads Budget Management")
access_token = st.text_input("Meta Ads Access Token", type="password")
ad_account_id = st.text_input("Meta Ad Account ID")
total_monthly_budget = st.number_input("Total Monthly Budget Allocated ($)", min_value=0.0, step=1.0)

padding_option = st.selectbox(
    "Select Padding Percentage",
    ["1%", "2%", "3%", "4%", "5%", "Custom"],
    index=4
)
if padding_option == "Custom":
    custom_padding = st.number_input(
        "Enter Custom Padding (%)", min_value=0.0, max_value=100.0, step=1.0
    )
    padding_percent = 1 - (custom_padding / 100)
else:
    padding_percent = 1 - (int(padding_option.strip("%")) / 100)

date_range = st.date_input("Date Range", [datetime.now().replace(day=1), datetime.now()])
if len(date_range) == 2:
    start_date = date_range[0].strftime("%Y-%m-%d")
    end_date = date_range[1].strftime("%Y-%m-%d")
    remaining_days = calculate_remaining_days(date_range[1])

if access_token:
    meta_api = MetaAPI(access_token)

    if st.button("Fetch Meta Ads Data"):
        with st.spinner("Fetching data..."):
            campaigns_response = meta_api.fetch_campaigns_with_budgets(ad_account_id)
            if "error" in campaigns_response:
                st.error(f"Error fetching campaigns: {campaigns_response['error']}")
            else:
                all_data = []
                for campaign in campaigns_response.get("data", []):
                    campaign_budget = campaign.get("daily_budget")
                    if campaign_budget:
                        campaign_budget = int(campaign_budget) / 100
                        spend = meta_api.fetch_spend(campaign["id"], start_date, end_date)
                        all_data.append({
                            "Name": campaign["name"],
                            "Entity ID": campaign["id"],
                            "Daily Budget ($)": campaign_budget,
                            "Spend ($)": spend,
                            "Daily Spend %": 0.0,
                            "New Daily %": 0.0,
                            "New Daily Budget ($)": 0.0,
                        })
                st.session_state["campaign_data"] = pd.DataFrame(all_data)
                st.session_state["total_spend"] = sum(row["Spend ($)"] for row in all_data)
                st.session_state["remaining_budget"] = (total_monthly_budget - st.session_state["total_spend"]) * padding_percent
                st.session_state["remaining_days"] = remaining_days
                st.session_state["show_commit_buttons"] = False

if "campaign_data" in st.session_state:
    campaign_data = st.session_state["campaign_data"]
    total_spend = st.session_state["total_spend"]
    remaining_budget = st.session_state["remaining_budget"]
    remaining_days = st.session_state["remaining_days"]

    st.write("### Current Campaign Spend Data")
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

    AgGrid(
        campaign_data,
        gridOptions=grid_options,
        update_mode=GridUpdateMode.VALUE_CHANGED,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=True,
    )

    if st.button("Calculate New Daily Budgets"):
        campaign_data["New Daily Budget ($)"] = campaign_data["New Daily %"].apply(
            lambda x: round((x / 100 * remaining_budget) / remaining_days, 2)
        )
        st.session_state["campaign_data"] = campaign_data
        st.session_state["show_commit_buttons"] = True

    if st.session_state.get("show_commit_buttons", False):
        st.write("### Updated Campaigns Spend Data")
        for i, row in campaign_data.iterrows():
            st.write(f"Campaign: {row['Name']}")
            st.write(f"New Daily Budget: ${row['New Daily Budget ($)']:.2f}")

            if f"commit_{i}" not in st.session_state:
                st.session_state[f"commit_{i}"] = False

            if not st.session_state[f"commit_{i}"]:
                if st.button(f"Prepare to Commit {row['Name']}", key=f"prepare_{i}"):
                    st.session_state[f"commit_{i}"] = True

            if st.session_state[f"commit_{i}"]:
                if st.button(f"Commit {row['Name']}", key=f"button_commit_{i}"):
                    result = meta_api.update_budget(row["Entity ID"], row["New Daily Budget ($)"])
                    if "error" in result:
                        st.error(f"Failed to update {row['Name']}: {result['error']['message']}")
                    else:
                        st.success(f"Successfully updated {row['Name']}!")

        if "commit_all_ready" not in st.session_state:
            st.session_state["commit_all_ready"] = False

        if not st.session_state["commit_all_ready"]:
            if st.button("Prepare to Commit All Budgets"):
                st.session_state["commit_all_ready"] = True

        if st.session_state["commit_all_ready"]:
            if st.button("Commit All Budgets"):
                for _, row in campaign_data.iterrows():
                    result = meta_api.update_budget(row["Entity ID"], row["New Daily Budget ($)"])
                    if "error" in result:
                        st.error(f"Failed to update {row['Name']}: {result['error']['message']}")
                    else:
                        st.success(f"Successfully updated all budgets!")

    st.write("### Summary")
    st.write(f"**Total Spend for Selected Period:** ${total_spend:.2f}")
    st.write(f"**Total Budget Remaining ({int(padding_percent * 100)}%):** ${remaining_budget:.2f}")
    st.write(f"**Total Days Remaining in Month:** {remaining_days} days")
