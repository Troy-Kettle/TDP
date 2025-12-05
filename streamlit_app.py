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
from io import BytesIO

# Page configuration
st.set_page_config(
    page_title="TDP Data Insight",
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

def to_excel(df):
    """Convert dataframe to Excel file in memory."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
    output.seek(0)
    return output

@st.cache_data(show_spinner=False, ttl=3600)
def load_product_categories(file_path: str = 'TDP Product Code List.xlsx'):
    """Load product category mapping (Landscape vs Furniture) from product code list.
    Returns: dict mapping Description to Category ('Landscape' or 'Furniture')
    """
    if not os.path.exists(file_path):
        return {}
    try:
        df = pd.read_excel(file_path)
        # Column name has trailing space: 'Landscape or Furniture '
        category_col = [c for c in df.columns if 'landscape' in c.lower() or 'furniture' in c.lower()]
        if not category_col:
            return {}
        category_col = category_col[0]
        
        # Create mapping from Description to full category name using vectorized operations
        mask_l = df[category_col].str.strip().str.upper() == 'L'
        mask_f = df[category_col].str.strip().str.upper() == 'F'
        
        category_map = {}
        for desc in df.loc[mask_l & df['Description'].notna(), 'Description']:
            category_map[desc] = 'Landscape'
        for desc in df.loc[mask_f & df['Description'].notna(), 'Description']:
            category_map[desc] = 'Furniture'
        return category_map
    except Exception as e:
        return {}

@st.cache_resource(show_spinner="Loading data...")
def load_data_fast(excel_path: str, product_list_path: str = 'TDP Product Code List.xlsx'):
    """Load data with Parquet caching for fast subsequent loads.
    Uses @cache_resource to keep data in memory across reruns.
    """
    import hashlib
    
    # Create cache filename based on Excel file
    cache_file = excel_path.replace('.xlsx', '_cache.parquet')
    
    # Check if cache is valid (exists and newer than source)
    use_cache = False
    if os.path.exists(cache_file) and os.path.exists(excel_path):
        cache_mtime = os.path.getmtime(cache_file)
        excel_mtime = os.path.getmtime(excel_path)
        product_mtime = os.path.getmtime(product_list_path) if os.path.exists(product_list_path) else 0
        if cache_mtime > excel_mtime and cache_mtime > product_mtime:
            use_cache = True
    
    meta = {
        'file_path': excel_path,
        'loaded': False,
        'missing_columns': [],
        'last_modified': None,
        'row_count': 0,
        'column_count': 0,
        'data_completeness_pct': None,
        'from_cache': use_cache
    }
    
    if not os.path.exists(excel_path):
        return None, meta
    
    try:
        mtime = os.path.getmtime(excel_path)
        meta['last_modified'] = datetime.fromtimestamp(mtime)
        
        if use_cache:
            # Fast load from Parquet cache
            df = pd.read_parquet(cache_file)
        else:
            # Slow load from Excel, then cache
            df = pd.read_excel(excel_path, sheet_name='Data')
            
            # Convert date fields
            for date_col in ['Invoice Date', 'Order Date', 'Dispatch Date', 'Completed Date']:
                if date_col in df.columns:
                    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            
            # Fill numeric columns
            for num_col in ['Total Price', 'Qty', 'Weight (KG)', 'Price', 'Discount']:
                if num_col in df.columns:
                    df[num_col] = pd.to_numeric(df[num_col], errors='coerce').fillna(0)
            
            # Create calculated fields
            if 'Invoice Date' in df.columns:
                df['Year'] = df['Invoice Date'].dt.year
                df['Month'] = df['Invoice Date'].dt.month
                df['Quarter'] = df['Invoice Date'].dt.quarter
                df['Year-Month'] = df['Invoice Date'].dt.to_period('M').astype(str)
            
            # Add Product Category
            if 'Short Description' in df.columns:
                product_categories = load_product_categories(product_list_path)
                if product_categories:
                    df['Product Category'] = df['Short Description'].map(product_categories)
            
            # Save to Parquet cache
            try:
                df.to_parquet(cache_file, index=False)
            except:
                pass  # Caching failed, continue anyway
        
        meta['column_count'] = len(df.columns)
        meta['row_count'] = len(df)
        meta['missing_columns'] = [c for c in EXPECTED_COLUMNS if c not in df.columns]
        
        total_cells = df.shape[0] * df.shape[1]
        if total_cells:
            meta['data_completeness_pct'] = (1 - df.isna().sum().sum() / total_cells) * 100
        meta['loaded'] = True
        
        # Pre-compute unique values for filters (stored with the data)
        meta['unique_types'] = sorted([x for x in df['Type'].dropna().unique() if pd.notna(x)]) if 'Type' in df.columns else []
        meta['unique_statuses'] = sorted([x for x in df['STATUS'].dropna().unique() if pd.notna(x)]) if 'STATUS' in df.columns else []
        meta['unique_categories'] = sorted([x for x in df['Product Category'].dropna().unique() if pd.notna(x)]) if 'Product Category' in df.columns else []
        meta['unique_item_types'] = sorted([x for x in df['Item Type'].dropna().unique() if pd.notna(x)]) if 'Item Type' in df.columns else []
        meta['unique_furniture_groups'] = sorted([x for x in df['Furniture Group'].dropna().unique() if pd.notna(x)]) if 'Furniture Group' in df.columns else []
        
        # Pre-compute date range
        if 'Invoice Date' in df.columns and not df['Invoice Date'].isna().all():
            meta['min_date'] = df['Invoice Date'].min().date()
            meta['max_date'] = df['Invoice Date'].max().date()
        
        return df, meta
    except Exception as e:
        return None, meta

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

        # Add Product Category (Landscape/Furniture) based on product code list
        if 'Short Description' in df.columns:
            product_categories = load_product_categories()
            if product_categories:
                df['Product Category'] = df['Short Description'].map(product_categories)

        # Data completeness metric (proportion of non-null cells)
        total_cells = df.shape[0] * df.shape[1] if df.shape[0] and df.shape[1] else 0
        if total_cells:
            meta['data_completeness_pct'] = (1 - df.isna().sum().sum() / total_cells) * 100
        meta['loaded'] = True
        return df, meta
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return None, meta

def apply_filters(_df, date_start, date_end, selected_types, selected_statuses, 
                  selected_categories, selected_item_types, selected_furniture_groups):
    """Apply all filters in a single optimized pass using numpy boolean arrays.
    Note: _df prefix tells Streamlit not to hash the dataframe.
    Filter arguments are tuples for hashability/caching.
    """
    n = len(_df)
    # Use numpy array for faster boolean operations
    mask = np.ones(n, dtype=bool)
    
    # Date filter
    if date_start is not None and date_end is not None:
        dates = _df['Invoice Date'].dt.date.values
        mask &= (dates >= date_start) & (dates <= date_end)
    
    # Type filter (include NaN)
    if selected_types:
        type_vals = _df['Type'].values
        mask &= np.isin(type_vals, selected_types) | pd.isna(type_vals)
    
    # Status filter (include NaN)
    if selected_statuses:
        status_vals = _df['STATUS'].values
        mask &= np.isin(status_vals, selected_statuses) | pd.isna(status_vals)
    
    # Product Category filter (include NaN)
    if selected_categories and 'Product Category' in _df.columns:
        cat_vals = _df['Product Category'].values
        mask &= np.isin(cat_vals, selected_categories) | pd.isna(cat_vals)
    
    # Item Type filter (include NaN)
    if selected_item_types:
        item_vals = _df['Item Type'].values
        mask &= np.isin(item_vals, selected_item_types) | pd.isna(item_vals)
    
    # Furniture Group filter (include NaN)
    if selected_furniture_groups and 'Furniture Group' in _df.columns:
        furn_vals = _df['Furniture Group'].values
        mask &= np.isin(furn_vals, selected_furniture_groups) | pd.isna(furn_vals)
    
    return _df.iloc[mask]

@st.cache_data(show_spinner=False)
def get_unique_values(df, column):
    """Get sorted unique non-null values from a column."""
    if column not in df.columns:
        return []
    return sorted([x for x in df[column].dropna().unique() if pd.notna(x)])

# Cached aggregation functions for charts
@st.cache_data(show_spinner=False)
def get_monthly_revenue(_hash, dates, prices):
    """Get monthly revenue aggregation. Cached."""
    if len(dates) == 0:
        return None
    df = pd.DataFrame({'date': pd.to_datetime(dates), 'price': prices})
    df = df.dropna(subset=['date'])
    if len(df) == 0:
        return None
    df['Month'] = df['date'].dt.to_period('M').astype(str)
    result = df.groupby('Month')['price'].sum().reset_index()
    result.columns = ['Month', 'Total Price']
    return result.sort_values('Month')

@st.cache_data(show_spinner=False)
def get_type_revenue(_hash, types, prices):
    """Get revenue by type. Cached."""
    if len(types) == 0:
        return None
    df = pd.DataFrame({'Type': types, 'Total Price': prices})
    result = df.groupby('Type', dropna=True)['Total Price'].sum().reset_index()
    return result.sort_values('Total Price', ascending=False)

@st.cache_data(show_spinner=False)
def get_quarterly_revenue(_hash, dates, prices):
    """Get quarterly revenue. Cached."""
    if len(dates) == 0:
        return None
    df = pd.DataFrame({'date': pd.to_datetime(dates), 'price': prices})
    df = df.dropna(subset=['date'])
    if len(df) == 0:
        return None
    df['Quarter'] = df['date'].dt.to_period('Q').astype(str)
    return df.groupby('Quarter')['price'].sum().reset_index().rename(columns={'price': 'Total Price'})

@st.cache_data(show_spinner=False)
def get_product_revenue(_hash, products, prices, qty):
    """Get revenue by product. Cached."""
    if len(products) == 0:
        return None
    df = pd.DataFrame({'Product': products, 'Total Price': prices, 'Qty': qty})
    result = df.groupby('Product', dropna=True).agg({'Total Price': 'sum', 'Qty': 'sum'}).reset_index()
    return result.sort_values('Total Price', ascending=False)

@st.cache_data(show_spinner=False)
def calculate_business_metrics(_df_hash, total_price, invoice_nos, customers, qty):
    """Calculate advanced business metrics and KPIs. Uses pre-computed arrays for speed."""
    metrics = {}
    
    metrics['total_revenue'] = total_price.sum() if len(total_price) > 0 else 0
    metrics['avg_transaction'] = total_price.mean() if len(total_price) > 0 else 0
    metrics['total_orders'] = len(set(invoice_nos)) if len(invoice_nos) > 0 else 0
    metrics['aov'] = metrics['total_revenue'] / metrics['total_orders'] if metrics['total_orders'] > 0 else 0
    metrics['total_customers'] = len(set(customers)) if len(customers) > 0 else 0
    metrics['revenue_per_customer'] = metrics['total_revenue'] / metrics['total_customers'] if metrics['total_customers'] > 0 else 0
    metrics['total_units'] = qty.sum() if len(qty) > 0 else 0
    metrics['avg_basket_size'] = qty.mean() if len(qty) > 0 else 0
    
    return metrics

@st.cache_data(show_spinner=False)
def period_over_period_analysis_cached(_df_hash, dates, prices):
    """Calculate period-over-period growth metrics. Cached version."""
    if len(dates) == 0 or len(prices) == 0:
        return None
    
    # Filter out NaT dates
    valid_mask = ~pd.isna(dates)
    dates = dates[valid_mask]
    prices = prices[valid_mask]
    
    if len(dates) == 0:
        return None
    
    current_date = pd.Timestamp(dates.max())
    
    results = {}
    
    # 30-day comparison
    d30 = current_date - timedelta(days=30)
    d60 = current_date - timedelta(days=60)
    
    current_30 = prices[dates >= d30].sum()
    previous_30 = prices[(dates >= d60) & (dates < d30)].sum()
    results['30_day_growth'] = ((current_30 - previous_30) / previous_30 * 100) if previous_30 > 0 else 0
    results['30_day_current'] = current_30
    results['30_day_previous'] = previous_30
    
    # 90-day comparison
    d90 = current_date - timedelta(days=90)
    d180 = current_date - timedelta(days=180)
    current_90 = prices[dates >= d90].sum()
    previous_90 = prices[(dates >= d180) & (dates < d90)].sum()
    results['90_day_growth'] = ((current_90 - previous_90) / previous_90 * 100) if previous_90 > 0 else 0
    
    # Year-over-year
    d365 = current_date - timedelta(days=365)
    d730 = current_date - timedelta(days=730)
    current_year = prices[dates >= d365].sum()
    previous_year = prices[(dates >= d730) & (dates < d365)].sum()
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

@st.cache_data(show_spinner=False, ttl=300)
def cohort_analysis(_df_hash, customers, dates, prices):
    """Perform cohort analysis based on first purchase month. Cached version."""
    if len(customers) == 0 or len(dates) == 0:
        return None
    
    # Create a dataframe from arrays
    df_cohort = pd.DataFrame({
        'Customer': customers,
        'Invoice Date': pd.to_datetime(dates),
        'Total Price': prices
    })
    
    # Filter valid rows
    df_cohort = df_cohort[df_cohort['Customer'].notna() & df_cohort['Invoice Date'].notna()]
    if len(df_cohort) == 0:
        return None
    
    df_cohort['OrderPeriod'] = df_cohort['Invoice Date'].dt.to_period('M')
    df_cohort['CohortPeriod'] = df_cohort.groupby('Customer')['Invoice Date'].transform('min').dt.to_period('M')
    
    df_cohort['CohortIndex'] = (df_cohort['OrderPeriod'] - df_cohort['CohortPeriod']).apply(lambda x: x.n)
    df_cohort['CohortPeriod'] = df_cohort['CohortPeriod'].astype(str)
    
    cohort_data = df_cohort.groupby(['CohortPeriod', 'CohortIndex']).agg({
        'Customer': 'nunique',
        'Total Price': 'sum'
    }).reset_index()
    
    cohort_pivot = cohort_data.pivot(index='CohortPeriod', columns='CohortIndex', values='Customer')
    if cohort_pivot.empty or len(cohort_pivot.columns) == 0:
        return None
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

    # Load data with FAST Parquet caching
    data_file = 'TDP Invoice Items Report - Troy Version.xlsx'
    df_original, meta = load_data_fast(data_file)
    if df_original is None:
        st.error(f"Data file not found: {data_file}")
        return

    # Sidebar filters
    st.sidebar.header("Filters")
    
    # Use pre-computed unique values from meta (already calculated during load)
    all_types = meta.get('unique_types', [])
    all_statuses = meta.get('unique_statuses', [])
    all_categories = meta.get('unique_categories', [])
    all_item_types = meta.get('unique_item_types', [])
    all_furniture_groups = meta.get('unique_furniture_groups', [])
    
    # Date range filter - always visible
    date_start, date_end = None, None
    if 'min_date' in meta and 'max_date' in meta:
        min_date = meta['min_date']
        max_date = meta['max_date']
        date_range = st.sidebar.date_input(
            "Date Range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )
        
        if len(date_range) == 2:
            date_start, date_end = date_range[0], date_range[1]
    
    st.sidebar.markdown("---")
    
    # FAST filters using multiselect (much faster than many checkboxes)
    # Product Category Filter - PRIMARY FILTER
    if all_categories:
        selected_categories = st.sidebar.multiselect(
            "Product Category",
            options=all_categories,
            default=all_categories,
            key='filter_categories'
        )
    else:
        selected_categories = []
    
    # Customer Type Filter
    selected_types = st.sidebar.multiselect(
        "Customer Type",
        options=all_types,
        default=all_types,
        key='filter_types'
    )
    
    # Order Status Filter
    selected_statuses = st.sidebar.multiselect(
        "Order Status",
        options=all_statuses,
        default=all_statuses,
        key='filter_statuses'
    )
    
    # Additional filters in expander
    with st.sidebar.expander("More Filters", expanded=False):
        # Item Type Filter
        selected_item_types = st.multiselect(
            "Item Type",
            options=all_item_types,
            default=all_item_types,
            key='filter_item_types'
        )
        
        # Furniture Group Filter
        if all_furniture_groups:
            selected_furniture_groups = st.multiselect(
                "Furniture Group",
                options=all_furniture_groups,
                default=all_furniture_groups,
                key='filter_furniture'
            )
        else:
            selected_furniture_groups = []
    
    # Apply all filters in one optimized pass
    df = apply_filters(
        df_original, 
        date_start, date_end,
        tuple(selected_types) if selected_types else None,
        tuple(selected_statuses) if selected_statuses else None,
        tuple(selected_categories) if selected_categories else None,
        tuple(selected_item_types) if selected_item_types else None,
        tuple(selected_furniture_groups) if selected_furniture_groups else None
    )
    
    # Main content area
    if len(df) == 0:
        st.warning("No data matches the selected filters.")
        return
    
    # Create a hash for caching based on filter selections
    filter_hash = hash((
        date_start, date_end,
        tuple(selected_types) if selected_types else None,
        tuple(selected_statuses) if selected_statuses else None,
        tuple(selected_categories) if selected_categories else None,
        tuple(selected_item_types) if selected_item_types else None,
        tuple(selected_furniture_groups) if selected_furniture_groups else None
    ))
    
    # Calculate business metrics (cached)
    metrics = calculate_business_metrics(
        filter_hash,
        df['Total Price'].values if 'Total Price' in df.columns else np.array([]),
        df['Invoice No'].values if 'Invoice No' in df.columns else np.array([]),
        df['Company/Individual'].values if 'Company/Individual' in df.columns else np.array([]),
        df['Qty'].values if 'Qty' in df.columns else np.array([])
    )
    
    # Period over period analysis (cached)
    pop_analysis = period_over_period_analysis_cached(
        filter_hash,
        df['Invoice Date'].values if 'Invoice Date' in df.columns else np.array([]),
        df['Total Price'].values if 'Total Price' in df.columns else np.array([])
    )
    
    # Create tabs for different sections
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Overview", 
        "Revenue Analysis", 
        "Customer Intelligence", 
        "Product Performance",
        "Geographic & Payment",
        "Forecasting"
    ])
    
    # TAB 1: OVERVIEW
    with tab1:
        # Data Health / Freshness Panel
        with st.expander("Data Health & Freshness", expanded=True):
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
            
            # Show filtering impact
            st.markdown("---")
            cols = st.columns(3)
            with cols[0]:
                st.metric("Total Rows (Raw)", f"{meta['row_count']:,}")
            with cols[1]:
                st.metric("Rows After Filters", f"{len(df):,}")
            with cols[2]:
                pct_included = (len(df) / meta['row_count'] * 100) if meta['row_count'] > 0 else 0
                st.metric("% Included", f"{pct_included:.1f}%")

            st.caption("Note: Filters now include rows with missing/NULL values in filter columns to ensure complete revenue calculation.")
        
        # Key Performance Indicators
        col_header, col_export = st.columns([4, 1])
        with col_header:
            st.markdown("### Key Performance Indicators")
        with col_export:
            # Export filtered data
            excel_data = to_excel(df)
            st.download_button(
                label="Export Filtered Data",
                data=excel_data,
                file_name=f"tdp_filtered_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        
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
                delta_colour = "normal" if growth_30 >= 0 else "inverse"
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
        col_header, col_export = st.columns([4, 1])
        with col_header:
            st.header("Revenue & Sales Analysis")
        with col_export:
            # Export monthly revenue data
            monthly_revenue = get_monthly_revenue(
                filter_hash,
                df['Invoice Date'].values if 'Invoice Date' in df.columns else np.array([]),
                df['Total Price'].values if 'Total Price' in df.columns else np.array([])
            )
            if monthly_revenue is not None:
                excel_revenue = to_excel(monthly_revenue)
                st.download_button(
                    label="Export Revenue Data",
                    data=excel_revenue,
                    file_name=f"monthly_revenue_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        
        col1, col2 = st.columns(2)
        
        with col1:
            monthly_revenue = get_monthly_revenue(
                filter_hash,
                df['Invoice Date'].values if 'Invoice Date' in df.columns else np.array([]),
                df['Total Price'].values if 'Total Price' in df.columns else np.array([])
            )
            if monthly_revenue is not None:
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
            type_revenue = get_type_revenue(
                filter_hash,
                df['Type'].values if 'Type' in df.columns else np.array([]),
                df['Total Price'].values if 'Total Price' in df.columns else np.array([])
            )
            if type_revenue is not None:
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
            # Quarterly revenue comparison (cached)
            quarterly_rev = get_quarterly_revenue(
                filter_hash,
                df['Invoice Date'].values if 'Invoice Date' in df.columns else np.array([]),
                df['Total Price'].values if 'Total Price' in df.columns else np.array([])
            )
            if quarterly_rev is not None:
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
        col_header, col_export = st.columns([4, 1])
        with col_header:
            st.header("Customer Intelligence")
        
        # Customer Value Analysis
        customer_data = customer_value_analysis(df)
        if customer_data is not None:
            with col_export:
                # Export customer data
                excel_customers = to_excel(customer_data)
                st.download_button(
                    label="Export Customer Data",
                    data=excel_customers,
                    file_name=f"customer_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            
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
        cohort_data = cohort_analysis(
            filter_hash,
            df['Company/Individual'].values if 'Company/Individual' in df.columns else np.array([]),
            df['Invoice Date'].values if 'Invoice Date' in df.columns else np.array([]),
            df['Total Price'].values if 'Total Price' in df.columns else np.array([])
        )
        
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
    
    # TAB 4: PRODUCT PERFORMANCE
    with tab4:
        col_header, col_export = st.columns([4, 1])
        with col_header:
            st.header("Product Performance")
        with col_export:
            # Export product data
            if 'Short Description' in df.columns and 'Total Price' in df.columns:
                product_export = df.groupby('Short Description').agg({
                    'Total Price': 'sum',
                    'Qty': 'sum' if 'Qty' in df.columns else 'count'
                }).reset_index().sort_values('Total Price', ascending=False)
                excel_products = to_excel(product_export)
                st.download_button(
                    label="Export Product Data",
                    data=excel_products,
                    file_name=f"product_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        
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
    
    # TAB 5: GEOGRAPHIC & PAYMENT
    with tab5:
        col_header, col_export = st.columns([4, 1])
        with col_header:
            st.header("Geographic Insights")
        with col_export:
            # Export geographic data
            if 'Delivery Town' in df.columns and 'Total Price' in df.columns:
                geo_export = df.groupby('Delivery Town')['Total Price'].sum().reset_index().sort_values('Total Price', ascending=False)
                excel_geo = to_excel(geo_export)
                st.download_button(
                    label="Export Geographic Data",
                    data=excel_geo,
                    file_name=f"geographic_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        
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
    
    # TAB 6: FORECASTING
    with tab6:
        col_header, col_export = st.columns([4, 1])
        with col_header:
            st.header("Revenue Forecasting")
        
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
                xgb_forecast = ml_results['xgboost']
                
                # Add export button for forecast
                with col_export:
                    # Combine historical and forecast data
                    forecast_export = pd.concat([
                        monthly_data[['Invoice Date', 'Total Price']].rename(columns={'Invoice Date': 'Date', 'Total Price': 'Revenue'}),
                        xgb_forecast.rename(columns={'Forecast': 'Revenue'})
                    ])
                    forecast_export['Type'] = ['Historical'] * len(monthly_data) + ['Forecast'] * len(xgb_forecast)
                    excel_forecast = to_excel(forecast_export)
                    st.download_button(
                        label="Export Forecast Data",
                        data=excel_forecast,
                        file_name=f"revenue_forecast_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
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
        st.markdown('<div class="insight-box"><b>Insight:</b> Predict future demand for top-selling products to optimise inventory and procurement planning.</div>', unsafe_allow_html=True)
        
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