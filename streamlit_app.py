import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
from functools import lru_cache
import time

# Function to calculate remaining days in the current month
@lru_cache(None)
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

    def fetch_adsets_with_budgets(self, campaign_id):
        url = f"https://graph.facebook.com/v15.0/{campaign_id}/adsets"
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

# Initialize session state
if "commit_ready" not in st.session_state:
    st.session_state["commit_ready"] = {}

if "meta_api" not in st.session_state:
    st.session_state["meta_api"] = None

if "campaign_data" not in st.session_state:
    st.session_state["campaign_data"] = None

if "show_commit_buttons" not in st.session_state:
    st.session_state["show_commit_buttons"] = False

# Platform selection
selected_platforms = st.multiselect(
    "Select Platform(s) to Adjust Budgets For",
    options=["Meta Ads", "Google Ads"],
)

# Meta Ads Functionality
if "Meta Ads" in selected_platforms:
    st.subheader("Meta Ads Budget and Spend Viewer")
    access_token = st.text_input("Meta Ads Access Token", type="password")
    ad_account_id = st.text_input("Ad Account ID")
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
        st.session_state["meta_api"] = MetaAPI(access_token)

    if st.button("Fetch Meta Ads Data"):
        meta_api = st.session_state["meta_api"]
        campaigns_response = meta_api.fetch_campaigns_with_budgets(ad_account_id)
        if "error" in campaigns_response:
            st.error(f"Error fetching campaigns: {campaigns_response['error']}")
        else:
            # Process campaigns and ad sets
            all_data = []
            total_items = len(campaigns_response.get("data", []))
            progress_bar = st.progress(0)

            for index, campaign in enumerate(campaigns_response.get("data", []), start=1):
                # Check if the campaign has a budget
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
                else:
                    # Fetch ad sets if the campaign lacks a budget
                    adsets_response = meta_api.fetch_adsets_with_budgets(campaign["id"])
                    for adset in adsets_response.get("data", []):
                        adset_budget = adset.get("daily_budget")
                        if adset_budget:
                            adset_budget = int(adset_budget) / 100
                            spend = meta_api.fetch_spend(adset["id"], start_date, end_date)
                            all_data.append({
                                "Name": adset["name"],
                                "Entity ID": adset["id"],
                                "Daily Budget ($)": adset_budget,
                                "Spend ($)": spend,
                                "Daily Spend %": 0.0,
                                "New Daily %": 0.0,
                                "New Daily Budget ($)": 0.0,
                            })
                # Update progress bar
                progress_bar.progress(index / total_items)

            # Calculate percentages
            total_daily_budget = sum(row["Daily Budget ($)"] for row in all_data)
            for row in all_data:
                row["Daily Spend %"] = round((row["Daily Budget ($)"] / total_daily_budget) * 100, 2) if total_daily_budget > 0 else 0
                row["New Daily %"] = row["Daily Spend %"]

            st.session_state["campaign_data"] = pd.DataFrame(all_data)
            st.session_state["total_spend"] = sum(row["Spend ($)"] for row in all_data)
            st.session_state["remaining_budget"] = (total_monthly_budget - st.session_state["total_spend"]) * padding_percent
            st.session_state["remaining_days"] = remaining_days
            st.session_state["show_commit_buttons"] = False
            st.success("Data successfully fetched!")

    if st.session_state["campaign_data"] is not None:
        campaign_data = st.session_state["campaign_data"]
        meta_api = st.session_state["meta_api"]
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
            st.success("Budgets calculated successfully!")

        if st.session_state["show_commit_buttons"]:
            st.write("### Updated Campaigns Spend Data")
            total_items = len(campaign_data)
            progress_bar = st.progress(0)

            for index, row in campaign_data.iterrows():
                st.write(f"Campaign: {row['Name']}")
                st.write(f"New Daily Budget: ${row['New Daily Budget ($)']:.2f}")

                if st.button(f"Commit {row['Name']}", key=f"button_commit_{index}"):
                    with st.spinner(f"Committing changes for {row['Name']}..."):
                        result = meta_api.update_budget(row["Entity ID"], row["New Daily Budget ($)"])
                        if "error" in result:
                            st.error(f"Failed to update {row['Name']}: {result['error']['message']}")
                        else:
                            st.success(f"Successfully updated {row['Name']}!")

                # Update progress bar for each commit
                progress_bar.progress((index + 1) / total_items)

            if st.button("Commit All Budgets"):
                progress_bar = st.progress(0)
                for index, row in campaign_data.iterrows():
                    result = meta_api.update_budget(row["Entity ID"], row["New Daily Budget ($)"])
                    if "error" in result:
                        st.error(f"Failed to update {row['Name']}: {result['error']['message']}")
                    else:
                        st.success(f"Successfully updated all budgets!")
                    progress_bar.progress((index + 1) / total_items)

        st.write("### Summary")
        st.write(f"**Total Spend for Selected Period:** ${total_spend:.2f}")
        st.write(f"**Total Budget Remaining ({int(padding_percent * 100)}%):** ${remaining_budget:.2f}")
        st.write(f"**Total Days Remaining in Month:** {remaining_days} days")

# Google Ads Placeholder
if "Google Ads" in selected_platforms:
    st.subheader("Google Ads Budget and Spend Viewer")
    st.info("Google Ads functionality coming soon!")
