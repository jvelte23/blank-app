import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
import os
import json

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
        # Load client from JSON credentials file
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
                    "id": campaign.id,
                    "name": campaign.name,
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
                campaign_id = row.campaign.id
                cost = row.metrics.cost_micros / 1_000_000  # Convert micros to standard units
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

# Streamlit UI
st.title("Campaign Budget Management for Meta Ads and Google Ads")

# Platform selection
selected_platforms = st.multiselect(
    "Select Platform(s) to Adjust Budgets For",
    options=["Meta Ads", "Google Ads"],
)

# Meta Ads Functionality
if "Meta Ads" in selected_platforms:
    st.subheader("Meta Ads Budget Management")
    access_token = st.text_input("Meta Ads Access Token", type="password")
    ad_account_id = st.text_input("Meta Ad Account ID")
    total_monthly_budget = st.number_input("Total Monthly Budget Allocated ($)", min_value=0.0, step=1.0)

    date_range = st.date_input("Date Range", [datetime.now().replace(day=1), datetime.now()])
    if len(date_range) == 2:
        start_date = date_range[0].strftime("%Y-%m-%d")
        end_date = date_range[1].strftime("%Y-%m-%d")
        remaining_days = calculate_remaining_days(date_range[1])

    if access_token:
        meta_api = MetaAPI(access_token)
        if st.button("Fetch Meta Ads Data"):
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
                st.success("Meta Ads data fetched successfully!")

# Google Ads Functionality
if "Google Ads" in selected_platforms:
    st.subheader("Google Ads Budget Management")
    customer_id = st.text_input("Google Ads Customer ID")
    total_monthly_budget = st.number_input("Google Ads Total Monthly Budget ($)", min_value=0.0, step=1.0)

    # Fetch JSON credentials from GitHub Secrets
    credentials_json = os.getenv("GOOGLE_ADS_CREDENTIALS")
    credentials_path = "/tmp/google_ads_credentials.json"

    if credentials_json:
        try:
            # Parse escaped JSON string and write it to a file
            credentials_data = json.loads(credentials_json)
            with open(credentials_path, "w") as f:
                json.dump(credentials_data, f)
            st.success("Credentials loaded successfully!")
        except Exception as e:
            st.error(f"Error loading credentials: {e}")
    else:
        st.error("Google Ads credentials not found in environment variables.")

    # Proceed if credentials are valid
    if os.path.exists(credentials_path):
        google_ads_api = GoogleAdsAPI(credentials_path)

        date_range = st.date_input("Date Range", [datetime.now().replace(day=1), datetime.now()])
        if len(date_range) == 2:
            start_date = date_range[0].strftime("%Y-%m-%d")
            end_date = date_range[1].strftime("%Y-%m-%d")
            remaining_days = calculate_remaining_days(date_range[1])

        if st.button("Fetch Google Ads Data"):
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

            st.session_state["campaign_data"] = pd.DataFrame(all_data)
            st.success("Google Ads data fetched successfully!")

# Shared Logic for Campaign Data Management
if "campaign_data" in st.session_state:
    campaign_data = st.session_state["campaign_data"]

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
            lambda x: round((x / 100 * total_monthly_budget) / remaining_days, 2)
        )
        st.write("### Updated Campaign Data")
        st.write(campaign_data)

    if st.button("Commit All Budgets"):
        st.write("Committing all changes...")
