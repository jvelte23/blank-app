import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
from functools import lru_cache
from google.ads.google_ads.client import GoogleAdsClient
from google.ads.google_ads.errors import GoogleAdsException
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

# Google Ads API Wrapper Class
class GoogleAdsAPI:
    def __init__(self, credentials_path):
        self.client = GoogleAdsClient.load_from_storage(credentials_path)

    def fetch_campaigns_with_budgets(self, customer_id):
        service = self.client.get_service("GoogleAdsService")
        query = """
            SELECT
              campaign.id,
              campaign.name,
              campaign_budget.amount_micros
            FROM
              campaign
            WHERE
              campaign.status = 'ENABLED'
        """
        response = service.search_stream(customer_id=customer_id, query=query)
        data = []
        for batch in response:
            for row in batch.results:
                campaign = row.campaign
                campaign_budget = row.campaign_budget
                data.append({
                    "id": campaign.id.value,
                    "name": campaign.name.value,
                    "daily_budget": campaign_budget.amount_micros / 1_000_000  # Convert micros to standard units
                })
        return data

    def fetch_spend(self, customer_id, start_date, end_date):
        service = self.client.get_service("GoogleAdsService")
        query = f"""
            SELECT
              campaign.id,
              metrics.cost_micros
            FROM
              campaign
            WHERE
              metrics.date >= '{start_date}' AND metrics.date <= '{end_date}'
        """
        response = service.search_stream(customer_id=customer_id, query=query)
        spend_data = {}
        for batch in response:
            for row in batch.results:
                campaign_id = row.campaign.id.value
                cost = row.metrics.cost_micros.value / 1_000_000  # Convert micros to standard units
                spend_data[campaign_id] = cost
        return spend_data

    def update_budget(self, customer_id, campaign_id, new_budget):
        campaign_service = self.client.get_service("CampaignBudgetService")
        budget_operation = self.client.get_type("CampaignBudgetOperation")
        budget_operation.update.resource_name = campaign_service.campaign_budget_path(customer_id, campaign_id)
        budget_operation.update.amount_micros = int(new_budget * 1_000_000)  # Convert to micros
        try:
            campaign_service.mutate_campaign_budget(customer_id=customer_id, operations=[budget_operation])
            return {"success": True}
        except GoogleAdsException as ex:
            return {"error": str(ex)}

# Initialize session state
if "commit_ready" not in st.session_state:
    st.session_state["commit_ready"] = {}

if "meta_api" not in st.session_state:
    st.session_state["meta_api"] = None

if "google_ads_api" not in st.session_state:
    st.session_state["google_ads_api"] = None

if "campaign_data" not in st.session_state:
    st.session_state["campaign_data"] = None

if "show_commit_buttons" not in st.session_state:
    st.session_state["show_commit_buttons"] = False

# Platform selection
selected_platforms = st.multiselect(
    "Select Platform(s) to Adjust Budgets For",
    options=["Meta Ads", "Google Ads"],
)

# Google Ads Functionality
if "Google Ads" in selected_platforms:
    st.subheader("Google Ads Budget and Spend Viewer")
    credentials_path = st.text_input("Google Ads Credentials JSON Path")
    customer_id = st.text_input("Google Ads Customer ID")
    total_monthly_budget = st.number_input("Total Monthly Budget Allocated ($)", min_value=0.0, step=1.0)

    date_range = st.date_input("Date Range", [datetime.now().replace(day=1), datetime.now()])
    if len(date_range) == 2:
        start_date = date_range[0].strftime("%Y-%m-%d")
        end_date = date_range[1].strftime("%Y-%m-%d")
        remaining_days = calculate_remaining_days(date_range[1])

    if credentials_path:
        st.session_state["google_ads_api"] = GoogleAdsAPI(credentials_path)

    if st.button("Fetch Google Ads Data"):
        google_ads_api = st.session_state["google_ads_api"]
        campaigns = google_ads_api.fetch_campaigns_with_budgets(customer_id)
        spend_data = google_ads_api.fetch_spend(customer_id, start_date, end_date)

        all_data = []
        for campaign in campaigns:
            campaign_id = campaign["id"]
            spend = spend_data.get(campaign_id, 0)
            all_data.append({
                "Name": campaign["name"],
                "Entity ID": campaign_id,
                "Daily Budget ($)": campaign["daily_budget"],
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

        st.session_state["campaign_data"] = pd.DataFrame(all_data)
        st.session_state["total_spend"] = sum(row["Spend ($)"] for row in all_data)
        st.session_state["remaining_budget"] = (total_monthly_budget - st.session_state["total_spend"])
        st.session_state["remaining_days"] = remaining_days
        st.session_state["show_commit_buttons"] = False
        st.success("Google Ads data fetched successfully!")

    if st.session_state["campaign_data"] is not None:
        campaign_data = st.session_state["campaign_data"]
        google_ads_api = st.session_state["google_ads_api"]
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
            for i, row in campaign_data.iterrows():
                st.write(f"Campaign: {row['Name']}")
                st.write(f"New Daily Budget: ${row['New Daily Budget ($)']:.2f}")

                if st.button(f"Commit {row['Name']}", key=f"google_commit_{i}"):
                    with st.spinner(f"Committing changes for {row['Name']}..."):
                        result = google_ads_api.update_budget(customer_id, row["Entity ID"], row["New Daily Budget ($)"])
                        if "error" in result:
                            st.error(f"Failed to update {row['Name']}: {result['error']}")
                        else:
                            st.success(f"Successfully updated {row['Name']}!")

            if st.button("Commit All Budgets"):
                with st.spinner("Committing all changes..."):
                    for _, row in campaign_data.iterrows():
                        result = google_ads_api.update_budget(customer_id, row["Entity ID"], row["New Daily Budget ($)"])
                        if "error" in result:
                            st.error(f"Failed to update {row['Name']}: {result['error']}")
                        else:
                            st.success(f"Successfully updated all budgets!")
