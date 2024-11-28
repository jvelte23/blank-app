import streamlit as st
import pandas as pd
import requests
from datetime import datetime

# Function to retrieve campaigns with budgets and spend for a custom date range
def get_campaigns_with_budgets_and_spend(access_token, ad_account_id, start_date, end_date):
    url = f"https://graph.facebook.com/v15.0/act_{ad_account_id}/campaigns"
    params = {
        'fields': 'id,name,daily_budget,lifetime_budget',
        'effective_status': '["ACTIVE"]',
        'access_token': access_token
    }
    response = requests.get(url, params=params)
    data = response.json()

    if 'error' in data:
        return None, data['error']['message']

    campaigns = []
    for campaign in data.get("data", []):
        if campaign.get("daily_budget") or campaign.get("lifetime_budget"):
            spend_url = f"https://graph.facebook.com/v15.0/{campaign['id']}/insights"
            spend_params = {
                'fields': 'spend',
                'time_range': '{"since":"' + start_date + '","until":"' + end_date + '"}',
                'access_token': access_token
            }
            spend_response = requests.get(spend_url, params=spend_params)
            spend_data = spend_response.json()
            spend = float(spend_data['data'][0]['spend']) if spend_data.get('data') else 0

            campaigns.append({
                "name": campaign["name"],
                "daily_budget": int(campaign.get("daily_budget", 0)) / 100,
                "spend": spend,
            })
    return campaigns, None

# Function to retrieve ad sets with budgets and spend for a custom date range
def get_ad_sets_with_budgets_and_spend(access_token, ad_account_id, start_date, end_date):
    url = f"https://graph.facebook.com/v15.0/act_{ad_account_id}/adsets"
    params = {
        'fields': 'id,name,daily_budget,lifetime_budget',
        'effective_status': '["ACTIVE"]',
        'access_token': access_token
    }
    response = requests.get(url, params=params)
    data = response.json()

    if 'error' in data:
        return None, data['error']['message']

    ad_sets = []
    for ad_set in data.get("data", []):
        if ad_set.get("daily_budget") or ad_set.get("lifetime_budget"):
            spend_url = f"https://graph.facebook.com/v15.0/{ad_set['id']}/insights"
            spend_params = {
                'fields': 'spend',
                'time_range': '{"since":"' + start_date + '","until":"' + end_date + '"}',
                'access_token': access_token
            }
            spend_response = requests.get(spend_url, params=spend_params)
            spend_data = spend_response.json()
            spend = float(spend_data['data'][0]['spend']) if spend_data.get('data') else 0

            ad_sets.append({
                "name": ad_set["name"],
                "daily_budget": int(ad_set.get("daily_budget", 0)) / 100,
                "spend": spend,
            })
    return ad_sets, None

# Function to calculate percentage of total spend
def calculate_percentage(data, total_spend):
    if total_spend == 0:
        return [0 for _ in data]
    return [(item["spend"] / total_spend) * 100 for item in data]

# Streamlit App
st.title("Meta Ads Budget and Spend Viewer")

# Input fields for access token and ad account ID
access_token = st.text_input("Meta Ads Access Token", type="password")
ad_account_id = st.text_input("Ad Account ID")

# Input field for total monthly budget allocated
total_monthly_budget = st.number_input("Total Monthly Budget Allocated ($)", min_value=0.0, step=1.0)

# Date range input
st.write("Select the date range for pulling spend data:")
date_range = st.date_input("Date Range", [datetime.now().replace(day=1), datetime.now()])

if len(date_range) == 2:
    start_date = date_range[0].strftime('%Y-%m-%d')
    end_date = date_range[1].strftime('%Y-%m-%d')

# Button to fetch data
if st.button("Fetch Budget and Spend Data"):
    if not access_token or not ad_account_id or len(date_range) != 2:
        st.error("Please provide all required inputs, including a valid date range.")
    else:
        st.write(f"Fetching data for the date range: {start_date} to {end_date}")

        # Fetch campaigns and ad sets with budgets and spend
        campaigns, campaigns_error = get_campaigns_with_budgets_and_spend(access_token, ad_account_id, start_date, end_date)
        ad_sets, ad_sets_error = get_ad_sets_with_budgets_and_spend(access_token, ad_account_id, start_date, end_date)

        if campaigns_error or ad_sets_error:
            if campaigns_error:
                st.error(f"Error fetching campaigns: {campaigns_error}")
            if ad_sets_error:
                st.error(f"Error fetching ad sets: {ad_sets_error}")
        else:
            # Combine campaigns and ad sets into one dataset
            data = campaigns + ad_sets

            # Calculate total spend and percentage allocation
            total_spend = sum(item["spend"] for item in data)
            remaining_budget = max(total_monthly_budget - total_spend, 0)
            percentage_allocation = calculate_percentage(data, total_spend)

            # Prepare data for the table
            table_data = pd.DataFrame([
                {
                    "Name": item["name"],
                    "Daily Budget ($)": f"${item['daily_budget']:.2f}",
                    "Spend ($)": f"${item['spend']:.2f}",
                    "Percentage of Total Spend": f"{percentage:.2f}%",
                    "New Daily %": 0.0,  # Default input for user
                    "New Daily Budget ($)": 0.0  # Placeholder for calculated value
                }
                for item, percentage in zip(data, percentage_allocation)
            ])

            # Add "New Daily %" input fields within the table
            new_daily_percentages = []
            for index, row in table_data.iterrows():
                new_percent = st.number_input(f"New Daily % for {row['Name']}", min_value=0.0, step=0.01, key=f"percent_{index}")
                new_daily_percentages.append(new_percent)

            # Update the table with the user-entered percentages
            table_data["New Daily %"] = new_daily_percentages

            # Add a button to calculate new daily budgets
            if st.button("Calculate New Daily Budgets"):
                table_data["New Daily Budget ($)"] = [
                    f"${(new_percent / 100) * remaining_budget:.2f}" for new_percent in new_daily_percentages
                ]

            # Display the table
            st.write("### Campaigns and Ad Sets Spend Data")
            st.dataframe(table_data)

            # Display total spend and remaining budget
            st.write(f"### Total Spend for Selected Period: ${total_spend:.2f}")
            st.write(f"### Total Budget Remaining: ${remaining_budget:.2f}")
