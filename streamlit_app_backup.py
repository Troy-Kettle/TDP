import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime, timedelta
import os
import re
from scipy import stats
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
try:
    from xgboost import XGBRegressor
    _HAS_XGBOOST = True
except ImportError:
    _HAS_XGBOOST = False
try:
    import pydeck as pdk
    _HAS_PYDECK = True
except ImportError:
    _HAS_PYDECK = False
import warnings
warnings.filterwarnings('ignore')

# Page configuration
st.set_page_config(
    page_title="TDP Data Insight",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Minimal CSS
st.markdown("""
<style>
    .main-header {
        color: #1f2937;
        text-align: center;
        padding: 1.5rem 0;
        margin-bottom: 1rem;
    }
    .insight-box {
        background-color: #f3f4f6;
        border-left: 3px solid #3b82f6;
        padding: 12px;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

EXPECTED_COLUMNS = [
    'Invoice No', 'Invoice Date', 'Order Date', 'Dispatch Date', 'Completed Date',
    'Company/Individual', 'Type', 'STATUS', 'Item Type', 'Short Description', 'Qty',
    'Price', 'Discount', 'Total Price', 'Weight (KG)', 'Delivery Town', 'Payment Method',
    'Production Status', 'Furniture Group'
]

@st.cache_data(show_spinner=False, ttl=3600)
def load_data(file_path: str):
    """Load and preprocess the Excel data.
    Returns: df (DataFrame or None), meta (dict with validation & freshness info)
    """
    meta = {
        'file_path': file_path,
        'loaded': False,
        'missing_columns': [],
        'last_modified': None,
        'row_count': 0,
        'column_count': 0,
        'data_completeness_pct': None
    }
    if not os.path.exists(file_path):
        st.error(f"Data file not found: {file_path}")
        return None, meta
    try:
        # Capture file modified time for freshness indicator
        mtime = os.path.getmtime(file_path)
        meta['last_modified'] = datetime.fromtimestamp(mtime)
        df = pd.read_excel(file_path, sheet_name='Data')

        # Track original columns & detect missing expected columns early
        meta['column_count'] = len(df.columns)
        meta['row_count'] = len(df)
        meta['missing_columns'] = [c for c in EXPECTED_COLUMNS if c not in df.columns]

        # Convert date fields that exist
        for date_col in ['Invoice Date', 'Order Date', 'Dispatch Date', 'Completed Date']:
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')

        # Fill numeric columns defensively
        for num_col in ['Total Price', 'Qty', 'Weight (KG)', 'Price', 'Discount']:
            if num_col in df.columns:
                df[num_col] = pd.to_numeric(df[num_col], errors='coerce').fillna(0)

        # Create additional calculated fields only if Invoice Date present
        if 'Invoice Date' in df.columns:
            df['Year'] = df['Invoice Date'].dt.year
            df['Month'] = df['Invoice Date'].dt.month
            df['Quarter'] = df['Invoice Date'].dt.quarter
            df['Year-Month'] = df['Invoice Date'].dt.to_period('M')

        # Data completeness metric (proportion of non-null cells)
        total_cells = df.shape[0] * df.shape[1] if df.shape[0] and df.shape[1] else 0
        if total_cells:
            meta['data_completeness_pct'] = (1 - df.isna().sum().sum() / total_cells) * 100
        meta['loaded'] = True
        return df, meta
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return None, meta

def calculate_business_metrics(df):
    """Calculate advanced business metrics and KPIs."""
    metrics = {}
    
    if 'Total Price' in df.columns:
        metrics['total_revenue'] = df['Total Price'].sum()
        metrics['avg_transaction'] = df['Total Price'].mean()
    
    if 'Invoice No' in df.columns:
        metrics['total_orders'] = df['Invoice No'].nunique()
        if 'Total Price' in df.columns:
            metrics['aov'] = metrics['total_revenue'] / metrics['total_orders'] if metrics['total_orders'] > 0 else 0
    
    if 'Company/Individual' in df.columns:
        metrics['total_customers'] = df['Company/Individual'].nunique()
        if 'Total Price' in df.columns:
            metrics['revenue_per_customer'] = metrics['total_revenue'] / metrics['total_customers'] if metrics['total_customers'] > 0 else 0
    
    if 'Qty' in df.columns:
        metrics['total_units'] = df['Qty'].sum()
        metrics['avg_basket_size'] = df['Qty'].mean()
    
    return metrics

def period_over_period_analysis(df):
    """Calculate period-over-period growth metrics."""
    if 'Invoice Date' not in df.columns or 'Total Price' not in df.columns:
        return None
    
    df_copy = df[df['Invoice Date'].notna()].copy()
    if len(df_copy) == 0:
        return None
    
    current_date = df_copy['Invoice Date'].max()
    
    # Define periods
    periods = {
        'last_30_days': current_date - timedelta(days=30),
        'previous_30_days': current_date - timedelta(days=60),
        'last_90_days': current_date - timedelta(days=90),
        'previous_90_days': current_date - timedelta(days=180),
        'last_year': current_date - timedelta(days=365),
        'previous_year': current_date - timedelta(days=730)
    }
    
    results = {}
    
    # 30-day comparison
    current_30 = df_copy[df_copy['Invoice Date'] >= periods['last_30_days']]['Total Price'].sum()
    previous_30 = df_copy[(df_copy['Invoice Date'] >= periods['previous_30_days']) & 
                          (df_copy['Invoice Date'] < periods['last_30_days'])]['Total Price'].sum()
    results['30_day_growth'] = ((current_30 - previous_30) / previous_30 * 100) if previous_30 > 0 else 0
    results['30_day_current'] = current_30
    results['30_day_previous'] = previous_30
    
    # 90-day comparison
    current_90 = df_copy[df_copy['Invoice Date'] >= periods['last_90_days']]['Total Price'].sum()
    previous_90 = df_copy[(df_copy['Invoice Date'] >= periods['previous_90_days']) & 
                          (df_copy['Invoice Date'] < periods['last_90_days'])]['Total Price'].sum()
    results['90_day_growth'] = ((current_90 - previous_90) / previous_90 * 100) if previous_90 > 0 else 0
    
    # Year-over-year
    current_year = df_copy[df_copy['Invoice Date'] >= periods['last_year']]['Total Price'].sum()
    previous_year = df_copy[(df_copy['Invoice Date'] >= periods['previous_year']) & 
                            (df_copy['Invoice Date'] < periods['last_year'])]['Total Price'].sum()
    results['yoy_growth'] = ((current_year - previous_year) / previous_year * 100) if previous_year > 0 else 0
    
    return results

def customer_value_analysis(df):
    """Analyse customer value by recency, frequency, and monetary metrics."""
    if not all(col in df.columns for col in ['Company/Individual', 'Invoice Date', 'Invoice No', 'Total Price']):
        return None
    
    df_analysis = df[df['Company/Individual'].notna()].copy()
    if len(df_analysis) == 0:
        return None
    
    current_date = df_analysis['Invoice Date'].max()
    
    customer_metrics = df_analysis.groupby('Company/Individual').agg({
        'Invoice Date': lambda x: (current_date - x.max()).days,
        'Invoice No': 'nunique',
        'Total Price': 'sum'
    }).reset_index()
    
    customer_metrics.columns = ['Customer', 'Days Since Last Purchase', 'Order Count', 'Total Revenue']
    
    return customer_metrics

def abc_analysis(df, column, value_column):
    """Perform ABC analysis on products or customers."""
    if column not in df.columns or value_column not in df.columns:
        return None
    
    analysis = df.groupby(column)[value_column].sum().reset_index()
    analysis = analysis.sort_values(value_column, ascending=False)
    analysis['Cumulative_Value'] = analysis[value_column].cumsum()
    analysis['Cumulative_Percentage'] = (analysis['Cumulative_Value'] / analysis[value_column].sum()) * 100
    
    # Classify into ABC categories
    def classify_abc(pct):
        if pct <= 80:
            return 'A'
        elif pct <= 95:
            return 'B'
        else:
            return 'C'
    
    analysis['Category'] = analysis['Cumulative_Percentage'].apply(classify_abc)
    
    return analysis

def cohort_analysis(df):
    """Perform cohort analysis based on first purchase month."""
    if not all(col in df.columns for col in ['Company/Individual', 'Invoice Date', 'Total Price']):
        return None
    
    df_cohort = df[df['Company/Individual'].notna() & df['Invoice Date'].notna()].copy()
    if len(df_cohort) == 0:
        return None
    
    df_cohort['OrderPeriod'] = df_cohort['Invoice Date'].dt.to_period('M')
    df_cohort['CohortPeriod'] = df_cohort.groupby('Company/Individual')['Invoice Date'].transform('min').dt.to_period('M')
    
    df_cohort['CohortIndex'] = (df_cohort['OrderPeriod'] - df_cohort['CohortPeriod']).apply(lambda x: x.n)
    df_cohort['CohortPeriod'] = df_cohort['CohortPeriod'].astype(str)
    
    cohort_data = df_cohort.groupby(['CohortPeriod', 'CohortIndex']).agg({
        'Company/Individual': 'nunique',
        'Total Price': 'sum'
    }).reset_index()
    
    cohort_pivot = cohort_data.pivot(index='CohortPeriod', columns='CohortIndex', values='Company/Individual')
    cohort_size = cohort_pivot.iloc[:, 0]
    retention = cohort_pivot.divide(cohort_size, axis=0) * 100
    
    return retention

@st.cache_data(show_spinner=False, ttl=1800)
def predict_revenue_ml(df, forecast_periods=6):
    """Machine learning revenue forecasting using multiple models."""
    if 'Invoice Date' not in df.columns or 'Total Price' not in df.columns:
        return None
    
    df_ml = df[df['Invoice Date'].notna() & df['Total Price'].notna()].copy()
    if len(df_ml) < 30:
        return None
    
    # Aggregate by month
    df_ml['YearMonth'] = df_ml['Invoice Date'].dt.to_period('M')
    monthly_data = df_ml.groupby('YearMonth').agg({
        'Total Price': 'sum',
        'Invoice No': 'nunique',
        'Qty': 'sum'
    }).reset_index()
    
    monthly_data['Invoice Date'] = monthly_data['YearMonth'].dt.to_timestamp()
    monthly_data = monthly_data.drop('YearMonth', axis=1).sort_values('Invoice Date')
    
    results = {'monthly_data': monthly_data}
    
    # XGBoost forecasting
    if _HAS_XGBOOST:
        try:
            monthly_data['Month'] = monthly_data['Invoice Date'].dt.month
            monthly_data['Year'] = monthly_data['Invoice Date'].dt.year
            monthly_data['MonthsSinceStart'] = (
                (monthly_data['Year'] - monthly_data['Year'].min()) * 12 + 
                monthly_data['Month']
            )
            
            features = ['Month', 'Year', 'MonthsSinceStart']
            X = monthly_data[features]
            y = monthly_data['Total Price']
            
            # Train-test split
            split_point = int(len(X) * 0.8)
            X_train, X_test = X[:split_point], X[split_point:]
            y_train, y_test = y[:split_point], y[split_point:]
            
            # Optimized for speed: fewer estimators, higher learning rate, lower depth
            model = XGBRegressor(
                n_estimators=50,
                learning_rate=0.1,
                max_depth=4,
                random_state=42,
                verbosity=0,
                n_jobs=1
            )
            model.fit(X_train, y_train)
            
            # Make predictions
            predictions = model.predict(X_test)
            
            # Future predictions
            last_date = monthly_data['Invoice Date'].max()
            future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1), periods=forecast_periods, freq='M')
            future_features = pd.DataFrame({
                'Month': future_dates.month,
                'Year': future_dates.year,
                'MonthsSinceStart': [
                    (d.year - monthly_data['Year'].min()) * 12 + d.month
                    for d in future_dates
                ]
            })
            
            future_predictions = model.predict(future_features)
            
            results['xgboost'] = pd.DataFrame({
                'Date': future_dates,
                'Forecast': future_predictions
            })
            
            results['model_train_score'] = r2_score(y_train, model.predict(X_train))
            results['model_test_score'] = r2_score(y_test, predictions)
            results['model_mae'] = mean_absolute_error(y_test, predictions)
            results['model_rmse'] = np.sqrt(mean_squared_error(y_test, predictions))
            
        except Exception as e:
            results['xgboost_error'] = str(e)
    else:
        results['xgboost_error'] = 'XGBoost not installed. Install with: pip install xgboost'
    
    return results

@st.cache_data(show_spinner=False, ttl=1800)
def predict_product_demand(df, forecast_periods=6, top_n=10):
    """Forecast demand for top products using XGBoost."""
    if 'Invoice Date' not in df.columns or 'Short Description' not in df.columns or 'Qty' not in df.columns:
        return None
    
    df_products = df[df['Invoice Date'].notna() & df['Short Description'].notna() & df['Qty'].notna()].copy()
    if len(df_products) < 30:
        return None
    
    # Get top N products by total quantity sold
    top_products = df_products.groupby('Short Description')['Qty'].sum().nlargest(top_n).index.tolist()
    
    results = {}
    
    if not _HAS_XGBOOST:
        return {'error': 'XGBoost not installed'}
    
    # Limit to fewer products for faster loading
    for product in top_products[:min(top_n, 5)]:
        try:
            product_df = df_products[df_products['Short Description'] == product].copy()
            
            # Aggregate by month
            product_df['YearMonth'] = product_df['Invoice Date'].dt.to_period('M')
            monthly_data = product_df.groupby('YearMonth').agg({
                'Qty': 'sum'
            }).reset_index()
            
            monthly_data['Invoice Date'] = monthly_data['YearMonth'].dt.to_timestamp()
            monthly_data = monthly_data.drop('YearMonth', axis=1).sort_values('Invoice Date')
            
            if len(monthly_data) < 6:
                continue
            
            # Create features
            monthly_data['Month'] = monthly_data['Invoice Date'].dt.month
            monthly_data['Year'] = monthly_data['Invoice Date'].dt.year
            monthly_data['MonthsSinceStart'] = (
                (monthly_data['Year'] - monthly_data['Year'].min()) * 12 + 
                monthly_data['Month']
            )
            
            features = ['Month', 'Year', 'MonthsSinceStart']
            X = monthly_data[features]
            y = monthly_data['Qty']
            
            # Optimized for speed: fewer estimators, higher learning rate, lower depth
            model = XGBRegressor(
                n_estimators=30,
                learning_rate=0.1,
                max_depth=3,
                random_state=42,
                verbosity=0,
                n_jobs=1
            )
            model.fit(X, y)
            
            # Future predictions
            last_date = monthly_data['Invoice Date'].max()
            future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1), periods=forecast_periods, freq='M')
            future_features = pd.DataFrame({
                'Month': future_dates.month,
                'Year': future_dates.year,
                'MonthsSinceStart': [
                    (d.year - monthly_data['Year'].min()) * 12 + d.month
                    for d in future_dates
                ]
            })
            
            future_predictions = model.predict(future_features)
            future_predictions = np.maximum(future_predictions, 0)  # No negative quantities
            
            results[product] = {
                'historical': monthly_data[['Invoice Date', 'Qty']],
                'forecast': pd.DataFrame({
                    'Date': future_dates,
                    'Forecast_Qty': future_predictions
                }),
                'total_forecast': future_predictions.sum()
            }
            
        except Exception as e:
            continue
    
    return results if results else None

def main():
    st.markdown('<h1 class="main-header">TDP Data Insight</h1>', unsafe_allow_html=True)

    # Load data with validation
    data_file = 'TDP Invoice Items Report - Troy Version.xlsx'
    df, meta = load_data(data_file)
    if df is None:
        return

    # Sidebar filters
    st.sidebar.header("🔍 Filters")
    
    # Store original dataframe for ML forecasting
    df_original = df.copy()
    
    # Date range filter - always visible
    if not df['Invoice Date'].isna().all():
        min_date = df['Invoice Date'].min().date()
        max_date = df['Invoice Date'].max().date()
        date_range = st.sidebar.date_input(
            "📅 Date Range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )
        
        if len(date_range) == 2:
            df = df[
                (df['Invoice Date'].dt.date >= date_range[0]) & 
                (df['Invoice Date'].dt.date <= date_range[1])
            ]
    
    st.sidebar.markdown("---")
    
    # Customer & Order Filters
    with st.sidebar.expander("👥 Customer & Orders", expanded=True):
        # Select All / Deselect All for Customer Type
        col1, col2 = st.columns(2)
        with col1:
            select_all_types = st.checkbox("Select All", value=True, key='select_all_types')
        
        customer_types = sorted([x for x in df['Type'].dropna().unique() if pd.notna(x)])
        selected_types = []
        
        # Display in 2 columns for compactness
        num_types = len(customer_types)
        mid = (num_types + 1) // 2
        col1, col2 = st.columns(2)
        
        for i, ctype in enumerate(customer_types):
            with col1 if i < mid else col2:
                if st.checkbox(ctype, value=select_all_types, key=f'type_{ctype}'):
                    selected_types.append(ctype)
        
        if selected_types:
            df = df[df['Type'].isin(selected_types)]
        
        st.markdown("---")
        
        # Select All / Deselect All for Order Status
        col1, col2 = st.columns(2)
        with col1:
            select_all_status = st.checkbox("Select All", value=True, key='select_all_status')
        
        statuses = sorted([x for x in df['STATUS'].dropna().unique() if pd.notna(x)])
        selected_statuses = []
        
        # Display in 2 columns
        num_status = len(statuses)
        mid = (num_status + 1) // 2
        col1, col2 = st.columns(2)
        
        for i, status in enumerate(statuses):
            with col1 if i < mid else col2:
                if st.checkbox(status, value=select_all_status, key=f'status_{status}'):
                    selected_statuses.append(status)
        
        if selected_statuses:
            df = df[df['STATUS'].isin(selected_statuses)]
    
    # Product Filters
    with st.sidebar.expander("📦 Products", expanded=False):
        # Select All / Deselect All for Item Type
        col1, col2 = st.columns(2)
        with col1:
            select_all_items = st.checkbox("Select All", value=True, key='select_all_items')
        
        item_types = sorted([x for x in df['Item Type'].dropna().unique() if pd.notna(x)])
        selected_item_types = []
        
        # Display in 2 columns
        num_items = len(item_types)
        mid = (num_items + 1) // 2
        col1, col2 = st.columns(2)
        
        for i, item_type in enumerate(item_types):
            with col1 if i < mid else col2:
                if st.checkbox(item_type, value=select_all_items, key=f'item_{item_type}'):
                    selected_item_types.append(item_type)
        
        if selected_item_types:
            df = df[df['Item Type'].isin(selected_item_types)]
        
        if 'Furniture Group' in df.columns:
            st.markdown("---")
            
            # Select All / Deselect All for Furniture Group
            col1, col2 = st.columns(2)
            with col1:
                select_all_furniture = st.checkbox("Select All", value=True, key='select_all_furniture')
            
            furniture_groups = sorted([x for x in df['Furniture Group'].dropna().unique() if pd.notna(x)])
            selected_furniture_groups = []
            
            # Display in 2 columns
            num_furniture = len(furniture_groups)
            mid = (num_furniture + 1) // 2
            col1, col2 = st.columns(2)
            
            for i, fgroup in enumerate(furniture_groups):
                with col1 if i < mid else col2:
                    if st.checkbox(fgroup, value=select_all_furniture, key=f'furniture_{fgroup}'):
                        selected_furniture_groups.append(fgroup)
            
            if selected_furniture_groups:
                df = df[df['Furniture Group'].isin(selected_furniture_groups)]
    
    # Main content area
    if len(df) == 0:
        st.warning("No data matches the selected filters.")
        return
    
    # Calculate business metrics
    metrics = calculate_business_metrics(df)
    pop_analysis = period_over_period_analysis(df)
    
    # Create tabs for different sections
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Overview", 
        "💰 Revenue Analysis", 
        "👥 Customer Intelligence", 
        "📦 Product Performance",
        "🌍 Geographic & Payment",
        "🤖 Forecasting"
    ])
    
    # TAB 1: OVERVIEW
    with tab1:
        # Data Health / Freshness Panel
        with st.expander("ℹ️ Data Health & Freshness", expanded=True):
            cols = st.columns(4)
            with cols[0]:
                st.metric("Rows", f"{meta['row_count']:,}")
            with cols[1]:
                st.metric("Columns", f"{meta['column_count']:,}")
            with cols[2]:
                if meta['data_completeness_pct'] is not None:
                    st.metric("Data Completeness", f"{meta['data_completeness_pct']:.1f}%")
            with cols[3]:
                if meta['last_modified']:
                    age = datetime.now() - meta['last_modified']
                    freshness = f"{age.days}d {age.seconds//3600}h ago"
                    st.metric("Last Updated", meta['last_modified'].strftime('%Y-%m-%d %H:%M'), help=f"File age: {freshness}")

            if meta['missing_columns']:
                st.warning(f"Missing expected columns: {', '.join(meta['missing_columns'])}. Some metrics may be unavailable.")
            else:
                st.success("All expected columns present.")

            st.caption("Definitions: Revenue = Sum of 'Total Price'. Average Order Value = Revenue / Unique invoices. Metrics exclude rows filtered out in sidebar.")
        
        # Key Performance Indicators
        st.markdown("### Key Performance Indicators")
        col1, col2, col3, col4, col5, col6 = st.columns(6)

        with col1:
            if 'total_revenue' in metrics:
                st.metric("Total Revenue", f"£{metrics['total_revenue']:,.0f}")
            else:
                st.metric("Total Revenue", "N/A")

        with col2:
            if 'total_orders' in metrics:
                st.metric("Total Orders", f"{metrics['total_orders']:,}")
            else:
                st.metric("Total Orders", "N/A")

        with col3:
            if 'aov' in metrics:
                st.metric("Average Order Value", f"£{metrics['aov']:,.0f}")
            else:
                st.metric("Average Order Value", "N/A")

        with col4:
            if 'total_customers' in metrics:
                st.metric("Unique Customers", f"{metrics['total_customers']:,}")
            else:
                st.metric("Unique Customers", "N/A")

        with col5:
            if 'total_units' in metrics:
                st.metric("Units Sold", f"{metrics['total_units']:,.0f}")
            else:
                st.metric("Units Sold", "N/A")

        with col6:
            if 'revenue_per_customer' in metrics:
                st.metric("Revenue per Customer", f"£{metrics['revenue_per_customer']:,.0f}")
            else:
                st.metric("Revenue per Customer", "N/A")
        
        # Growth metrics
        if pop_analysis:
            st.markdown("### Growth Trends")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                growth_30 = pop_analysis['30_day_growth']
                delta_color = "normal" if growth_30 >= 0 else "inverse"
                st.metric("30-Day Growth", f"{growth_30:+.1f}%", 
                         delta=f"£{pop_analysis['30_day_current']:,.0f} vs £{pop_analysis['30_day_previous']:,.0f}")
            
            with col2:
                growth_90 = pop_analysis['90_day_growth']
                st.metric("90-Day Growth", f"{growth_90:+.1f}%")
            
            with col3:
                growth_yoy = pop_analysis['yoy_growth']
                st.metric("Year-over-Year Growth", f"{growth_yoy:+.1f}%")
    
    # TAB 2: REVENUE ANALYSIS
    with tab2:
        st.header("📊 Revenue & Sales Analysis")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if 'Invoice Date' in df.columns and 'Total Price' in df.columns:
                temp = df[['Invoice Date', 'Total Price']].dropna(subset=['Invoice Date']).copy()
                temp['YearMonth'] = temp['Invoice Date'].dt.to_period('M').astype(str)
                monthly_revenue = temp.groupby('YearMonth')['Total Price'].sum().reset_index()
                monthly_revenue = monthly_revenue.sort_values('YearMonth')
                monthly_revenue = monthly_revenue.rename(columns={'YearMonth': 'Month'})

                fig_monthly = px.line(
                    monthly_revenue,
                    x='Month',
                    y='Total Price',
                    title='Monthly Revenue Trend',
                    labels={'Total Price': 'Revenue (£)', 'Month': 'Month'}
                )
                fig_monthly.update_traces(mode='lines+markers')
                fig_monthly.update_layout(height=400)
                st.plotly_chart(fig_monthly, use_container_width=True)
            else:
                st.info("Invoice Date / Total Price not available for time trend.")
        
        with col2:
            if 'Type' in df.columns and 'Total Price' in df.columns:
                type_revenue = df.groupby('Type', dropna=True)['Total Price'].sum().reset_index().sort_values('Total Price', ascending=False)
                fig_type = px.bar(
                    type_revenue,
                    x='Type',
                    y='Total Price',
                    title='Revenue by Customer Type',
                    labels={'Total Price': 'Revenue (£)', 'Type': 'Customer Type'}
                )
                fig_type.update_layout(height=400, xaxis_tickangle=30)
                st.plotly_chart(fig_type, use_container_width=True)
            else:
                st.info("Customer Type / Total Price not available.")
        
        # Additional revenue insights
        st.markdown("---")
        st.subheader("Revenue Breakdown & Trends")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Quarterly revenue comparison
            if 'Invoice Date' in df.columns and 'Total Price' in df.columns:
                temp = df[df['Invoice Date'].notna()].copy()
                temp['Quarter'] = temp['Invoice Date'].dt.to_period('Q').astype(str)
                quarterly_rev = temp.groupby('Quarter')['Total Price'].sum().reset_index()
                
                fig_quarterly = px.bar(
                    quarterly_rev,
                    x='Quarter',
                    y='Total Price',
                    title='Quarterly Revenue Performance',
                    labels={'Total Price': 'Revenue (£)', 'Quarter': 'Quarter'},
                    color='Total Price',
                    color_continuous_scale='Viridis'
                )
                fig_quarterly.update_layout(height=400, showlegend=False)
                st.plotly_chart(fig_quarterly, use_container_width=True)
        
        with col2:
            # Revenue by status
            if 'STATUS' in df.columns and 'Total Price' in df.columns:
                status_rev = df.groupby('STATUS', dropna=True)['Total Price'].sum().reset_index()
                status_rev = status_rev.sort_values('Total Price', ascending=False)
                
                fig_status = px.pie(
                    status_rev,
                    values='Total Price',
                    names='STATUS',
                    title='Revenue Distribution by Order Status',
                    hole=0.4
                )
                fig_status.update_layout(height=400)
                st.plotly_chart(fig_status, use_container_width=True)
    
    # TAB 3: CUSTOMER INTELLIGENCE
    with tab3:
        st.header("👥 Customer Intelligence")
        
        # Customer Value Analysis
        customer_data = customer_value_analysis(df)
        if customer_data is not None:
            st.subheader("Customer Performance Metrics")
            st.markdown('<div class="insight-box"><b>Insight:</b> Analyse customer behaviour based on purchase recency, order frequency, and total revenue contribution.</div>', unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
        
        with col1:
            # Top customers by revenue
            top_by_revenue = customer_data.nlargest(15, 'Total Revenue')
            
            fig_top_customers = px.bar(
                top_by_revenue,
                x='Total Revenue',
                y='Customer',
                orientation='h',
                title='Top 15 Customers by Revenue',
                labels={'Total Revenue': 'Revenue (£)', 'Customer': 'Customer'},
                color='Total Revenue',
                color_continuous_scale='Blues'
            )
            fig_top_customers.update_layout(height=500, showlegend=False)
            st.plotly_chart(fig_top_customers, use_container_width=True)
        
        with col2:
            # Customer recency analysis
            fig_recency = px.histogram(
                customer_data,
                x='Days Since Last Purchase',
                title='Customer Purchase Recency',
                labels={'Days Since Last Purchase': 'Days Since Last Purchase', 'count': 'Number of Customers'},
                nbins=30
            )
            fig_recency.update_layout(height=500, showlegend=False)
            st.plotly_chart(fig_recency, use_container_width=True)
        
        # Top customers table
        st.subheader("Top 20 Customers by Revenue")
        top_customers = customer_data.sort_values('Total Revenue', ascending=False).head(20)
        st.dataframe(
            top_customers,
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Customer analysis requires Customer, Invoice Date, Invoice No, and Total Price columns.")
    
    # ABC Analysis
    st.markdown("---")
    st.subheader("ABC Analysis - Customer Value Distribution")
    abc_customers = abc_analysis(df, 'Company/Individual', 'Total Price')
    
    if abc_customers is not None:
        st.markdown('<div class="insight-box"><b>Insight:</b> ABC analysis shows that typically 80% of revenue comes from 20% of customers (Pareto principle).</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Category distribution
            cat_dist = abc_customers['Category'].value_counts().reset_index()
            cat_dist.columns = ['Category', 'Count']
            
            fig_abc = px.bar(
                cat_dist,
                x='Category',
                y='Count',
                title='ABC Category Distribution',
                labels={'Count': 'Number of Customers', 'Category': 'ABC Category'},
                color='Category',
                color_discrete_map={'A': '#28a745', 'B': '#ffc107', 'C': '#dc3545'}
            )
            fig_abc.update_layout(height=400)
            st.plotly_chart(fig_abc, use_container_width=True)
        
        with col2:
            # Cumulative revenue curve
            fig_cum = px.line(
                abc_customers.head(50),
                x=abc_customers.head(50).index,
                y='Cumulative_Percentage',
                title='Cumulative Revenue Curve (Top 50 Customers)',
                labels={'Cumulative_Percentage': 'Cumulative Revenue %', 'index': 'Customer Rank'}
            )
            fig_cum.add_hline(y=80, line_dash="dash", line_color="red", annotation_text="80% Revenue")
            fig_cum.update_layout(height=400)
            st.plotly_chart(fig_cum, use_container_width=True)
    
    # Cohort Analysis
    st.markdown("---")
    st.subheader("Customer Retention Cohort Analysis")
    cohort_data = cohort_analysis(df)
    
    if cohort_data is not None:
        st.markdown('<div class="insight-box"><b>Insight:</b> Cohort analysis tracks customer retention over time, showing what percentage of customers from each cohort continue purchasing.</div>', unsafe_allow_html=True)
        
        # Heatmap of retention
        fig_cohort = px.imshow(
            cohort_data,
            labels=dict(x="Months Since First Purchase", y="Cohort Month", color="Retention %"),
            title="Customer Retention Heatmap",
            color_continuous_scale='RdYlGn',
            aspect='auto'
        )
        fig_cohort.update_layout(height=500)
        st.plotly_chart(fig_cohort, use_container_width=True)
    else:
        st.info("Cohort analysis requires Customer, Invoice Date, and Total Price columns.")
    
    st.markdown("---")
    
    # Product Performance
    st.header("📦 Product Performance")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if 'Short Description' in df.columns and 'Total Price' in df.columns:
            product_revenue = df.groupby('Short Description')['Total Price'].sum().reset_index()
            product_revenue = product_revenue.sort_values('Total Price', ascending=False).head(10)
            fig_products = px.bar(
                product_revenue,
                x='Total Price',
                y='Short Description',
                orientation='h',
                title='Top 10 Products by Revenue',
                labels={'Total Price': 'Revenue (£)', 'Short Description': 'Product'}
            )
            fig_products.update_layout(height=500)
            st.plotly_chart(fig_products, use_container_width=True)
        else:
            st.info("Product description / revenue columns missing.")
    
    with col2:
        if 'Item Type' in df.columns:
            item_type_counts = df['Item Type'].value_counts(dropna=True).reset_index()
            item_type_counts.columns = ['Item Type', 'Count']
            fig_items = px.pie(
                item_type_counts,
                values='Count',
                names='Item Type',
                title='Distribution by Item Type'
            )
            fig_items.update_layout(height=500)
            st.plotly_chart(fig_items, use_container_width=True)
        else:
            st.info("Item Type column not available.")
    
    # Product ABC Analysis
    st.markdown("---")
    st.subheader("ABC Analysis - Product Value Distribution")
    abc_products = abc_analysis(df, 'Short Description', 'Total Price')
    
    if abc_products is not None:
        st.markdown('<div class="insight-box"><b>Insight:</b> Focus inventory management and marketing efforts on Category A products (top 20% generating 80% of revenue).</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            cat_summary = abc_products.groupby('Category').agg({
                'Short Description': 'count',
                'Total Price': 'sum'
            }).reset_index()
            cat_summary.columns = ['Category', 'Product Count', 'Revenue']
            
            fig_abc_prod = px.bar(
                cat_summary,
                x='Category',
                y='Revenue',
                title='Revenue by ABC Category',
                text='Product Count',
                labels={'Revenue': 'Revenue (£)', 'Category': 'ABC Category'},
                color='Category',
                color_discrete_map={'A': '#28a745', 'B': '#ffc107', 'C': '#dc3545'}
            )
            fig_abc_prod.update_traces(texttemplate='%{text} products', textposition='outside')
            fig_abc_prod.update_layout(height=400)
            st.plotly_chart(fig_abc_prod, use_container_width=True)
        
        with col2:
            # Top 15 products
            st.dataframe(
                abc_products.head(15)[['Short Description', 'Total Price', 'Category']],
                use_container_width=True,
                hide_index=True
            )
    
    # Quantity vs Revenue Analysis
    if 'Qty' in df.columns and 'Short Description' in df.columns and 'Total Price' in df.columns:
        st.markdown("---")
        st.subheader("Volume vs Value Analysis")
        
        product_metrics = df.groupby('Short Description').agg({
            'Qty': 'sum',
            'Total Price': 'sum'
        }).reset_index()
        product_metrics = product_metrics.sort_values('Total Price', ascending=False).head(20)
        
        fig_scatter = px.scatter(
            product_metrics,
            x='Qty',
            y='Total Price',
            hover_name='Short Description',
            title='Top 20 Products: Quantity Sold vs Revenue Generated',
            labels={'Qty': 'Units Sold', 'Total Price': 'Revenue (£)'},
            size='Total Price',
            color='Total Price',
            color_continuous_scale='Viridis'
        )
        fig_scatter.update_layout(height=500)
        st.plotly_chart(fig_scatter, use_container_width=True)
    
    st.markdown("---")
    
    # Geographic Insights
    st.header("🌍 Geographic Insights")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Revenue by Geographic Region")
        if 'Delivery Town' in df.columns and 'Total Price' in df.columns:
            town_revenue = df.groupby('Delivery Town')['Total Price'].sum().reset_index()
            town_revenue = town_revenue.sort_values('Total Price', ascending=False).head(15)
            
            fig_town = px.bar(
                town_revenue,
                x='Total Price',
                y='Delivery Town',
                orientation='h',
                title='Top 15 Towns by Revenue',
                labels={'Total Price': 'Revenue (£)', 'Delivery Town': 'Town'},
                color='Total Price',
                color_continuous_scale='Viridis'
            )
            fig_town.update_layout(height=500, showlegend=False)
            st.plotly_chart(fig_town, use_container_width=True)
        else:
            st.info("Geographic data not available.")
    
    with col2:
        st.subheader("Payment Methods")
        if 'Payment Method' in df.columns and 'Total Price' in df.columns:
            payment_revenue = df.groupby('Payment Method')['Total Price'].sum().reset_index()
            fig_payment = px.pie(
                payment_revenue,
                values='Total Price',
                names='Payment Method',
                title='Revenue by Payment Method',
                hole=0.4
            )
            fig_payment.update_layout(height=500)
            st.plotly_chart(fig_payment, use_container_width=True)
        else:
            st.info("Payment method data not available.")
    
    st.markdown("---")
    
    # Revenue Forecasting
    st.header("🤖 Revenue Forecasting")
    st.markdown('<div class="insight-box"><b>Insight:</b> XGBoost uses gradient boosting to predict future revenue based on historical patterns and seasonality.</div>', unsafe_allow_html=True)
    
    # Forecasting controls
    col1, col2 = st.columns([1, 3])
    with col1:
        forecast_months = st.slider("Forecast Horizon (Months)", 3, 12, 6)
    
    # Generate forecasts
    ml_results = predict_revenue_ml(df_original, forecast_periods=forecast_months)
    
    if ml_results and 'monthly_data' in ml_results:
        monthly_data = ml_results['monthly_data']
        
        # Check if XGBoost forecast available
        if 'xgboost' in ml_results:
            # Historical revenue trend
            st.subheader("Historical Revenue Trend")
            fig_hist = px.line(
                monthly_data,
                x='Invoice Date',
                y='Total Price',
                title='Monthly Revenue - Historical Data',
                labels={'Total Price': 'Revenue (£)', 'Invoice Date': 'Month'}
            )
            fig_hist.update_traces(mode='lines+markers')
            fig_hist.update_layout(height=400)
            st.plotly_chart(fig_hist, use_container_width=True)
            
            # XGBoost forecast
            st.subheader("Revenue Forecast")
            
            xgb_forecast = ml_results['xgboost']
            
            forecast_fig = go.Figure()
            
            # Add historical data
            forecast_fig.add_trace(go.Scatter(
                x=monthly_data['Invoice Date'],
                y=monthly_data['Total Price'],
                mode='lines+markers',
                name='Historical Revenue',
                line=dict(color='#667eea', width=3)
            ))
            
            # Add XGBoost forecast
            forecast_fig.add_trace(go.Scatter(
                x=xgb_forecast['Date'],
                y=xgb_forecast['Forecast'],
                mode='lines+markers',
                name='XGBoost Forecast',
                line=dict(color='#28a745', width=3, dash='dash')
            ))
            
            forecast_fig.update_layout(
                title='Revenue Forecast - XGBoost Model',
                xaxis_title='Date',
                yaxis_title='Revenue (£)',
                height=500,
                hovermode='x unified'
            )
            st.plotly_chart(forecast_fig, use_container_width=True)
            
            # Model performance metrics
            if 'model_test_score' in ml_results:
                st.subheader("Model Performance Metrics")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("R² Score (Test)", f"{ml_results['model_test_score']:.3f}")
                with col2:
                    st.metric("MAE", f"£{ml_results['model_mae']:,.0f}")
                with col3:
                    st.metric("RMSE", f"£{ml_results['model_rmse']:,.0f}")
                with col4:
                    st.metric("R² Score (Train)", f"{ml_results['model_train_score']:.3f}")
            
            # Forecast table
            st.subheader("Detailed Forecast Values")
            forecast_table = xgb_forecast.copy()
            forecast_table['Date'] = forecast_table['Date'].dt.strftime('%B %Y')
            forecast_table['Forecast'] = forecast_table['Forecast'].apply(lambda x: f"£{x:,.0f}")
            st.dataframe(forecast_table, use_container_width=True, hide_index=True)
        
        elif 'xgboost_error' in ml_results:
            st.error(f"XGBoost Error: {ml_results['xgboost_error']}")
            st.info("To install XGBoost, run: pip install xgboost")
        else:
            st.warning("XGBoost forecast not available.")
    else:
        st.warning("Insufficient data for forecasting. At least 30 historical data points are required.")
    
    # Product Demand Forecasting
    st.markdown("---")
    st.header("Product Demand Forecasting")
    st.markdown('<div class="insight-box"><b>Insight:</b> Predict future demand for top-selling products to optimize inventory and procurement planning.</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns([1, 3])
    with col1:
        forecast_months_products = st.slider("Product Forecast Horizon (Months)", 3, 12, 6, key='product_forecast')
        top_n_products = st.slider("Number of Products to Forecast", 5, 20, 10)
    
    product_forecasts = predict_product_demand(df_original, forecast_periods=forecast_months_products, top_n=top_n_products)
    
    if product_forecasts and 'error' not in product_forecasts:
        # Summary table of forecasted demand
        st.subheader("Forecasted Product Demand Summary")
        
        summary_data = []
        for product, data in product_forecasts.items():
            historical_avg = data['historical']['Qty'].mean()
            forecast_total = data['total_forecast']
            summary_data.append({
                'Product': product,
                'Historical Avg (Monthly)': f"{historical_avg:.0f}",
                f'Total Forecast ({forecast_months_products}mo)': f"{forecast_total:.0f}",
                'Avg Forecast (Monthly)': f"{forecast_total/forecast_months_products:.0f}"
            })
        
        summary_df = pd.DataFrame(summary_data)
        st.dataframe(summary_df, use_container_width=True, hide_index=True)
        
        # Individual product forecasts
        st.subheader("Detailed Product Forecasts")
        
        # Select product to view
        product_names = list(product_forecasts.keys())
        selected_product = st.selectbox("Select Product to View Forecast", product_names)
        
        if selected_product:
            product_data = product_forecasts[selected_product]
            
            # Create combined chart
            fig_product = go.Figure()
            
            # Historical data
            fig_product.add_trace(go.Scatter(
                x=product_data['historical']['Invoice Date'],
                y=product_data['historical']['Qty'],
                mode='lines+markers',
                name='Historical Demand',
                line=dict(color='#667eea', width=2)
            ))
            
            # Forecast
            fig_product.add_trace(go.Scatter(
                x=product_data['forecast']['Date'],
                y=product_data['forecast']['Forecast_Qty'],
                mode='lines+markers',
                name='Forecasted Demand',
                line=dict(color='#28a745', width=2, dash='dash')
            ))
            
            fig_product.update_layout(
                title=f'Demand Forecast: {selected_product}',
                xaxis_title='Date',
                yaxis_title='Quantity',
                height=400,
                hovermode='x unified'
            )
            st.plotly_chart(fig_product, use_container_width=True)
            
            # Forecast table
            forecast_table = product_data['forecast'].copy()
            forecast_table['Date'] = forecast_table['Date'].dt.strftime('%B %Y')
            forecast_table['Forecast_Qty'] = forecast_table['Forecast_Qty'].apply(lambda x: f"{x:.0f} units")
            forecast_table.columns = ['Month', 'Forecasted Quantity']
            st.dataframe(forecast_table, use_container_width=True, hide_index=True)
    
    elif product_forecasts and 'error' in product_forecasts:
        st.error(f"Error: {product_forecasts['error']}")
    else:
        st.warning("Insufficient data for product forecasting. Requires at least 30 data points with Product, Date, and Quantity information.")

if __name__ == "__main__":
    main()
