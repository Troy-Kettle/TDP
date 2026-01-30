import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, timedelta
import os
import warnings
warnings.filterwarnings('ignore')
from io import BytesIO


# Page configuration - minimal setup
st.set_page_config(
    page_title="TDP Data Insight",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Minimal CSS - reduced for speed
st.markdown("""
<style>
    .main-header {color: #1f2937; text-align: center; padding: 1rem 0;}
    .insight-box {background-color: #f3f4f6; border-left: 3px solid #3b82f6; padding: 10px; margin: 8px 0;}
</style>
""", unsafe_allow_html=True)

# Plotly config for fast rendering - disable unnecessary features
PLOTLY_CONFIG = {
    'displayModeBar': False,
    'staticPlot': False,
    'responsive': True
}

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

def get_file_mtime(file_path: str) -> float:
    """Get file modification time, returns 0 if file doesn't exist."""
    try:
        return os.path.getmtime(file_path) if os.path.exists(file_path) else 0
    except:
        return 0

def refresh_data_from_source(file_path: str) -> tuple[bool, str]:
    """
    Refresh data from source. Currently re-reads from Excel file.
    Will be updated to pull from SQL database directly.
    
    Returns: (success: bool, message: str)
    """
    # Check if we're in Docker/Linux (no win32com available)
    import platform
    if platform.system() != 'Windows':
        # In Docker - just clear cache to re-read Excel file
        return True, "Data cache refreshed"
    
    # On Windows - try to refresh Excel data connections
    try:
        import win32com.client
        import pythoncom
    except ImportError:
        # pywin32 not installed - just clear cache
        return True, "Data cache refreshed"
    
    if not os.path.exists(file_path):
        return False, f"File not found: {file_path}"
    
    excel = None
    workbook = None
    try:
        # Initialize COM for this thread (required in Streamlit)
        pythoncom.CoInitialize()
        
        # Get absolute path
        abs_path = os.path.abspath(file_path)
        
        # Create Excel application instance
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = False  # Run in background
        excel.DisplayAlerts = False  # Suppress prompts
        
        # Open the workbook
        workbook = excel.Workbooks.Open(abs_path)
        
        # Refresh all data connections
        workbook.RefreshAll()
        
        # Wait for refresh to complete (background queries)
        excel.CalculateUntilAsyncQueriesDone()
        
        # Save the workbook
        workbook.Save()
        
        return True, "Excel data refreshed from SQL database"
        
    except Exception as e:
        return False, f"Error refreshing Excel: {str(e)}"
        
    finally:
        # Clean up
        try:
            if workbook:
                workbook.Close(SaveChanges=False)
            if excel:
                excel.Quit()
        except:
            pass
        
        # Uninitialize COM
        try:
            pythoncom.CoUninitialize()
        except:
            pass

@st.cache_data(show_spinner=False, ttl=3600)
def load_product_categories(file_path: str = 'TDP Product Code List.xlsx', _file_mtime: float = 0):
    """Load product category mapping."""
    if not os.path.exists(file_path):
        return {}
    try:
        df = pd.read_excel(file_path)
        category_col = [c for c in df.columns if 'landscape' in c.lower() or 'furniture' in c.lower()]
        if not category_col:
            return {}
        category_col = category_col[0]
        
        category_map = {}
        mask_l = df[category_col].str.strip().str.upper() == 'L'
        mask_f = df[category_col].str.strip().str.upper() == 'F'
        
        for desc in df.loc[mask_l & df['Description'].notna(), 'Description']:
            category_map[desc] = 'Landscape'
        for desc in df.loc[mask_f & df['Description'].notna(), 'Description']:
            category_map[desc] = 'Furniture'
        return category_map
    except:
        return {}

@st.cache_data(show_spinner="Loading data...", ttl=300)
def load_data_fast(excel_path: str, product_list_path: str = 'TDP Product Code List.xlsx', _file_mtime: float = 0):
    """Load data with Parquet caching for fast subsequent loads.
    _file_mtime parameter ensures cache invalidates when file changes.
    """
    cache_file = excel_path.replace('.xlsx', '_cache.parquet')
    
    use_cache = False
    if os.path.exists(cache_file) and os.path.exists(excel_path):
        cache_mtime = os.path.getmtime(cache_file)
        excel_mtime = os.path.getmtime(excel_path)
        product_mtime = os.path.getmtime(product_list_path) if os.path.exists(product_list_path) else 0
        if cache_mtime > excel_mtime and cache_mtime > product_mtime:
            use_cache = True
    
    meta = {
        'file_path': excel_path, 'loaded': False, 'missing_columns': [],
        'last_modified': None, 'row_count': 0, 'column_count': 0,
        'data_completeness_pct': None, 'from_cache': use_cache
    }
    
    if not os.path.exists(excel_path):
        return None, meta
    
    try:
        mtime = os.path.getmtime(excel_path)
        meta['last_modified'] = datetime.fromtimestamp(mtime)
        
        if use_cache:
            df = pd.read_parquet(cache_file)
        else:
            df = pd.read_excel(excel_path, sheet_name='Data')
            
            for date_col in ['Invoice Date', 'Order Date', 'Dispatch Date', 'Completed Date']:
                if date_col in df.columns:
                    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            
            for num_col in ['Total Price', 'Qty', 'Weight (KG)', 'Price', 'Discount']:
                if num_col in df.columns:
                    df[num_col] = pd.to_numeric(df[num_col], errors='coerce').fillna(0)
            
            if 'Invoice Date' in df.columns:
                df['Year'] = df['Invoice Date'].dt.year
                df['Month'] = df['Invoice Date'].dt.month
                df['Quarter'] = df['Invoice Date'].dt.quarter
                df['Year-Month'] = df['Invoice Date'].dt.to_period('M').astype(str)
            
            if 'Short Description' in df.columns:
                prod_mtime = get_file_mtime(product_list_path)
                product_categories = load_product_categories(product_list_path, _file_mtime=prod_mtime)
                if product_categories:
                    df['Product Category'] = df['Short Description'].map(product_categories)
            
            try:
                df.to_parquet(cache_file, index=False)
            except:
                pass
        
        meta['column_count'] = len(df.columns)
        meta['row_count'] = len(df)
        meta['missing_columns'] = [c for c in EXPECTED_COLUMNS if c not in df.columns]
        
        total_cells = df.shape[0] * df.shape[1]
        if total_cells:
            meta['data_completeness_pct'] = (1 - df.isna().sum().sum() / total_cells) * 100
        meta['loaded'] = True
        meta['loaded_at'] = datetime.now()
        
        # Pre-compute unique values for filters
        meta['unique_types'] = sorted([x for x in df['Type'].dropna().unique() if pd.notna(x)]) if 'Type' in df.columns else []
        meta['unique_statuses'] = sorted([x for x in df['STATUS'].dropna().unique() if pd.notna(x)]) if 'STATUS' in df.columns else []
        meta['unique_categories'] = sorted([x for x in df['Product Category'].dropna().unique() if pd.notna(x)]) if 'Product Category' in df.columns else []
        meta['unique_item_types'] = sorted([x for x in df['Item Type'].dropna().unique() if pd.notna(x)]) if 'Item Type' in df.columns else []
        meta['unique_furniture_groups'] = sorted([x for x in df['Furniture Group'].dropna().unique() if pd.notna(x)]) if 'Furniture Group' in df.columns else []
        meta['unique_colours'] = sorted([x for x in df['Colour'].dropna().unique() if pd.notna(x)]) if 'Colour' in df.columns else []
        
        if 'Invoice Date' in df.columns and not df['Invoice Date'].isna().all():
            meta['min_date'] = df['Invoice Date'].min().date()
            meta['max_date'] = df['Invoice Date'].max().date()
        
        return df, meta
    except Exception as e:
        return None, meta

def apply_filters(_df, date_start, date_end, selected_types, selected_statuses, 
                  selected_categories, selected_item_types, selected_furniture_groups):
    """Apply all filters in a single optimized pass using numpy boolean arrays."""
    n = len(_df)
    mask = np.ones(n, dtype=bool)
    
    if date_start is not None and date_end is not None:
        dates = _df['Invoice Date'].dt.date.values
        mask &= (dates >= date_start) & (dates <= date_end)
    
    if selected_types:
        type_vals = _df['Type'].values
        mask &= np.isin(type_vals, selected_types) | pd.isna(type_vals)
    
    if selected_statuses:
        status_vals = _df['STATUS'].values
        mask &= np.isin(status_vals, selected_statuses) | pd.isna(status_vals)
    
    if selected_categories and 'Product Category' in _df.columns:
        cat_vals = _df['Product Category'].values
        mask &= np.isin(cat_vals, selected_categories) | pd.isna(cat_vals)
    
    if selected_item_types:
        item_vals = _df['Item Type'].values
        mask &= np.isin(item_vals, selected_item_types) | pd.isna(item_vals)
    
    if selected_furniture_groups and 'Furniture Group' in _df.columns:
        furn_vals = _df['Furniture Group'].values
        mask &= np.isin(furn_vals, selected_furniture_groups) | pd.isna(furn_vals)
    
    return _df.iloc[mask]

# FAST cached aggregation functions
@st.cache_data(show_spinner=False)
def get_monthly_revenue(_hash, dates, prices):
    """Get monthly revenue aggregation - ultra fast."""
    if len(dates) == 0:
        return None
    df = pd.DataFrame({'date': pd.to_datetime(dates), 'price': prices})
    df = df.dropna(subset=['date'])
    if len(df) == 0:
        return None
    df['Month'] = df['date'].dt.to_period('M').astype(str)
    result = df.groupby('Month', as_index=False)['price'].sum()
    result.columns = ['Month', 'Total Price']
    return result.sort_values('Month')

@st.cache_data(show_spinner=False)
def get_type_revenue(_hash, types, prices):
    """Get revenue by type - ultra fast."""
    if len(types) == 0:
        return None
    df = pd.DataFrame({'Type': types, 'Total Price': prices})
    result = df.groupby('Type', dropna=True, as_index=False)['Total Price'].sum()
    return result.sort_values('Total Price', ascending=False)

@st.cache_data(show_spinner=False)
def get_quarterly_revenue(_hash, dates, prices):
    """Get quarterly revenue - ultra fast."""
    if len(dates) == 0:
        return None
    df = pd.DataFrame({'date': pd.to_datetime(dates), 'price': prices})
    df = df.dropna(subset=['date'])
    if len(df) == 0:
        return None
    df['Quarter'] = df['date'].dt.to_period('Q').astype(str)
    return df.groupby('Quarter', as_index=False)['price'].sum().rename(columns={'price': 'Total Price'})

@st.cache_data(show_spinner=False)
def calculate_business_metrics(_df_hash, total_price, invoice_nos, customers, qty):
    """Calculate business metrics - ultra fast using numpy."""
    metrics = {}
    metrics['total_revenue'] = float(np.nansum(total_price)) if len(total_price) > 0 else 0
    metrics['avg_transaction'] = float(np.nanmean(total_price)) if len(total_price) > 0 else 0
    metrics['total_orders'] = len(set(invoice_nos)) if len(invoice_nos) > 0 else 0
    metrics['aov'] = metrics['total_revenue'] / metrics['total_orders'] if metrics['total_orders'] > 0 else 0
    metrics['total_customers'] = len(set(customers)) if len(customers) > 0 else 0
    metrics['revenue_per_customer'] = metrics['total_revenue'] / metrics['total_customers'] if metrics['total_customers'] > 0 else 0
    metrics['total_units'] = float(np.nansum(qty)) if len(qty) > 0 else 0
    metrics['avg_basket_size'] = float(np.nanmean(qty)) if len(qty) > 0 else 0
    return metrics

@st.cache_data(show_spinner=False)
def period_over_period_analysis_cached(_df_hash, dates, prices):
    """Calculate period-over-period growth - ultra fast."""
    if len(dates) == 0 or len(prices) == 0:
        return None
    
    valid_mask = ~pd.isna(dates)
    dates = pd.to_datetime(dates[valid_mask])
    prices = np.array(prices)[valid_mask]
    
    if len(dates) == 0:
        return None
    
    current_date = dates.max()
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

@st.cache_data(show_spinner=False)
def customer_value_analysis_fast(_hash, customers, dates, invoice_nos, prices):
    """Customer value analysis - fast version."""
    if len(customers) == 0:
        return None
    
    df = pd.DataFrame({
        'Customer': customers,
        'Invoice Date': pd.to_datetime(dates),
        'Invoice No': invoice_nos,
        'Total Price': prices
    })
    df = df[df['Customer'].notna() & df['Invoice Date'].notna()]
    if len(df) == 0:
        return None
    
    current_date = df['Invoice Date'].max()
    
    customer_metrics = df.groupby('Customer', as_index=False).agg({
        'Invoice Date': lambda x: (current_date - x.max()).days,
        'Invoice No': 'nunique',
        'Total Price': 'sum'
    })
    customer_metrics.columns = ['Customer', 'Days Since Last Purchase', 'Order Count', 'Total Revenue']
    return customer_metrics

# Check for XGBoost availability
try:
    from xgboost import XGBRegressor
    _HAS_XGBOOST = True
except ImportError:
    _HAS_XGBOOST = False

# ADVANCED FORECASTING with XGBoost and seasonality
@st.cache_data(show_spinner=False, ttl=900)
def predict_revenue_advanced(dates, prices, forecast_periods=6):
    """Advanced revenue forecasting using XGBoost with seasonality and confidence intervals."""
    if len(dates) == 0 or len(prices) == 0:
        return None
    
    df = pd.DataFrame({'date': pd.to_datetime(dates), 'price': prices})
    df = df.dropna()
    if len(df) < 12:
        return None
    
    # Aggregate by month
    df['YearMonth'] = df['date'].dt.to_period('M')
    monthly = df.groupby('YearMonth', as_index=False)['price'].sum()
    monthly['date'] = monthly['YearMonth'].dt.to_timestamp()
    monthly = monthly.sort_values('date').reset_index(drop=True)
    
    if len(monthly) < 12:
        return None
    
    y = monthly['price'].values
    
    # Create rich feature set
    monthly['month'] = monthly['date'].dt.month
    monthly['year'] = monthly['date'].dt.year
    monthly['quarter'] = monthly['date'].dt.quarter
    monthly['months_since_start'] = np.arange(len(monthly))
    
    # Lag features (previous months' revenue)
    monthly['lag_1'] = monthly['price'].shift(1)
    monthly['lag_2'] = monthly['price'].shift(2)
    monthly['lag_3'] = monthly['price'].shift(3)
    monthly['lag_12'] = monthly['price'].shift(12)  # Same month last year
    
    # Rolling statistics
    monthly['rolling_mean_3'] = monthly['price'].rolling(3, min_periods=1).mean()
    monthly['rolling_mean_6'] = monthly['price'].rolling(6, min_periods=1).mean()
    monthly['rolling_std_3'] = monthly['price'].rolling(3, min_periods=1).std().fillna(0)
    
    # Year-over-year growth
    monthly['yoy_growth'] = monthly['price'].pct_change(12).fillna(0)
    
    # Seasonal indices (average for each month)
    monthly_avg = monthly.groupby('month')['price'].transform('mean')
    overall_avg = monthly['price'].mean()
    monthly['seasonal_index'] = monthly_avg / overall_avg if overall_avg > 0 else 1
    
    # Fill NaN values from lag features
    monthly = monthly.fillna(method='bfill').fillna(method='ffill').fillna(0)
    
    feature_cols = ['month', 'quarter', 'months_since_start', 'lag_1', 'lag_2', 'lag_3',
                    'rolling_mean_3', 'rolling_mean_6', 'rolling_std_3', 'seasonal_index']
    
    # Add lag_12 if we have enough data
    if len(monthly) > 12:
        feature_cols.append('lag_12')
        feature_cols.append('yoy_growth')
    
    X = monthly[feature_cols].values
    
    # Train/test split (use last 20% for testing)
    split_idx = max(int(len(X) * 0.8), len(X) - 6)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    results = {
        'monthly_data': monthly[['date', 'price']].rename(columns={'price': 'Total Price', 'date': 'Invoice Date'}),
    }
    
    if _HAS_XGBOOST and len(X_train) >= 6:
        # XGBoost model with good hyperparameters
        model = XGBRegressor(
            n_estimators=100,
            learning_rate=0.1,
            max_depth=4,
            min_child_weight=2,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=42,
            verbosity=0,
            n_jobs=-1
        )
        model.fit(X_train, y_train)
        
        # Evaluate on test set
        if len(X_test) > 0:
            y_pred_test = model.predict(X_test)
            mae = np.mean(np.abs(y_test - y_pred_test))
            rmse = np.sqrt(np.mean((y_test - y_pred_test)**2))
            ss_res = np.sum((y_test - y_pred_test)**2)
            ss_tot = np.sum((y_test - np.mean(y_test))**2)
            r2_test = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        else:
            mae, rmse, r2_test = 0, 0, 0
        
        # Calculate training R²
        y_pred_train = model.predict(X_train)
        ss_res_train = np.sum((y_train - y_pred_train)**2)
        ss_tot_train = np.sum((y_train - np.mean(y_train))**2)
        r2_train = 1 - (ss_res_train / ss_tot_train) if ss_tot_train > 0 else 0
        
        # Generate future predictions
        last_date = monthly['date'].max()
        future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1), periods=forecast_periods, freq='MS')
        
        # Build future features iteratively (each prediction uses previous predictions)
        future_predictions = []
        future_lower = []
        future_upper = []
        
        # Get seasonal indices for each month
        seasonal_indices = monthly.groupby('month')['seasonal_index'].first().to_dict()
        
        # Prepare rolling values
        recent_values = list(monthly['price'].tail(12).values)
        
        for i, future_date in enumerate(future_dates):
            future_month = future_date.month
            future_quarter = (future_month - 1) // 3 + 1
            months_since_start = len(monthly) + i
            
            # Update lag features with predictions
            lag_1 = recent_values[-1] if len(recent_values) >= 1 else y.mean()
            lag_2 = recent_values[-2] if len(recent_values) >= 2 else y.mean()
            lag_3 = recent_values[-3] if len(recent_values) >= 3 else y.mean()
            lag_12 = recent_values[-12] if len(recent_values) >= 12 else y.mean()
            
            rolling_mean_3 = np.mean(recent_values[-3:]) if len(recent_values) >= 3 else y.mean()
            rolling_mean_6 = np.mean(recent_values[-6:]) if len(recent_values) >= 6 else y.mean()
            rolling_std_3 = np.std(recent_values[-3:]) if len(recent_values) >= 3 else 0
            
            seasonal_idx = seasonal_indices.get(future_month, 1.0)
            
            future_features = [future_month, future_quarter, months_since_start, 
                             lag_1, lag_2, lag_3, rolling_mean_3, rolling_mean_6, 
                             rolling_std_3, seasonal_idx]
            
            if 'lag_12' in feature_cols:
                yoy_growth = (lag_1 - lag_12) / lag_12 if lag_12 > 0 else 0
                future_features.extend([lag_12, yoy_growth])
            
            pred = model.predict([future_features])[0]
            pred = max(pred, 0)  # No negative predictions
            
            future_predictions.append(pred)
            recent_values.append(pred)
            
            # Confidence intervals based on historical variance
            std_error = rmse if rmse > 0 else np.std(y) * 0.1
            confidence_factor = 1 + (i * 0.1)  # Uncertainty grows with forecast horizon
            future_lower.append(max(pred - 1.96 * std_error * confidence_factor, 0))
            future_upper.append(pred + 1.96 * std_error * confidence_factor)
        
        results['forecast'] = pd.DataFrame({
            'Date': future_dates,
            'Forecast': future_predictions,
            'Lower_CI': future_lower,
            'Upper_CI': future_upper
        })
        results['r2_train'] = r2_train
        results['r2_test'] = r2_test
        results['mae'] = mae
        results['rmse'] = rmse
        results['model_type'] = 'XGBoost'
        
        # Feature importance
        importance = dict(zip(feature_cols, model.feature_importances_))
        results['feature_importance'] = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True)[:5])
        
    else:
        # Fallback to enhanced linear regression with seasonality
        # Decompose into trend and seasonal components
        from collections import defaultdict
        
        # Calculate seasonal factors
        seasonal_factors = defaultdict(list)
        for idx, row in monthly.iterrows():
            seasonal_factors[row['month']].append(row['price'])
        
        monthly_averages = {m: np.mean(vals) for m, vals in seasonal_factors.items()}
        overall_mean = np.mean(list(monthly_averages.values()))
        seasonal_indices = {m: avg / overall_mean if overall_mean > 0 else 1 for m, avg in monthly_averages.items()}
        
        # Deseasonalize
        deseasonalized = y / np.array([seasonal_indices[m] for m in monthly['month']])
        
        # Fit trend on deseasonalized data
        x = np.arange(len(deseasonalized)).astype(float)
        n = len(x)
        m_coef = (n * np.sum(x * deseasonalized) - np.sum(x) * np.sum(deseasonalized)) / (n * np.sum(x**2) - np.sum(x)**2)
        b_coef = (np.sum(deseasonalized) - m_coef * np.sum(x)) / n
        
        # Predictions
        y_pred = (m_coef * x + b_coef) * np.array([seasonal_indices[m] for m in monthly['month']])
        
        # Metrics on test set
        if len(y) > 6:
            test_actual = y[-3:]
            test_pred = y_pred[-3:]
            mae = np.mean(np.abs(test_actual - test_pred))
            rmse = np.sqrt(np.mean((test_actual - test_pred)**2))
            ss_res = np.sum((test_actual - test_pred)**2)
            ss_tot = np.sum((test_actual - np.mean(test_actual))**2)
            r2_test = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        else:
            mae, rmse, r2_test = 0, 0, 0
        
        # R² on full data
        ss_res_full = np.sum((y - y_pred)**2)
        ss_tot_full = np.sum((y - np.mean(y))**2)
        r2_train = 1 - (ss_res_full / ss_tot_full) if ss_tot_full > 0 else 0
        
        # Future predictions
        last_date = monthly['date'].max()
        future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1), periods=forecast_periods, freq='MS')
        future_x = np.arange(len(monthly), len(monthly) + forecast_periods).astype(float)
        future_trend = m_coef * future_x + b_coef
        future_seasonal = np.array([seasonal_indices[d.month] for d in future_dates])
        future_predictions = future_trend * future_seasonal
        future_predictions = np.maximum(future_predictions, 0)
        
        # Confidence intervals
        std_error = rmse if rmse > 0 else np.std(y) * 0.15
        future_lower = np.maximum(future_predictions - 1.96 * std_error * np.arange(1, forecast_periods + 1) * 0.2, 0)
        future_upper = future_predictions + 1.96 * std_error * np.arange(1, forecast_periods + 1) * 0.2
        
        results['forecast'] = pd.DataFrame({
            'Date': future_dates,
            'Forecast': future_predictions,
            'Lower_CI': future_lower,
            'Upper_CI': future_upper
        })
        results['r2_train'] = r2_train
        results['r2_test'] = r2_test
        results['mae'] = mae
        results['rmse'] = rmse
        results['model_type'] = 'Seasonal Linear Regression'
        results['feature_importance'] = {'trend': 0.5, 'seasonality': 0.5}
    
    # Calculate trend direction and growth rate
    recent_trend = y[-6:] if len(y) >= 6 else y
    results['trend_direction'] = 'up' if np.polyfit(range(len(recent_trend)), recent_trend, 1)[0] > 0 else 'down'
    
    if len(y) >= 12:
        results['monthly_growth_rate'] = ((y[-1] / y[-12]) - 1) * 100 if y[-12] > 0 else 0
    else:
        results['monthly_growth_rate'] = ((y[-1] / y[0]) ** (12 / len(y)) - 1) * 100 if y[0] > 0 else 0
    
    return results

@st.cache_data(show_spinner=False, ttl=900)
def predict_product_demand_advanced(products, dates, qty, forecast_periods=6, top_n=5):
    """Advanced product demand forecasting using XGBoost with seasonality."""
    if len(products) == 0 or len(dates) == 0:
        return None
    
    df = pd.DataFrame({
        'Product': products,
        'date': pd.to_datetime(dates),
        'Qty': qty
    })
    df = df.dropna()
    if len(df) < 30:
        return None
    
    # Get top N products by quantity
    top_products = df.groupby('Product')['Qty'].sum().nlargest(top_n).index.tolist()
    
    results = {}
    for product in top_products:
        product_df = df[df['Product'] == product].copy()
        product_df['YearMonth'] = product_df['date'].dt.to_period('M')
        monthly = product_df.groupby('YearMonth', as_index=False)['Qty'].sum()
        monthly['date'] = monthly['YearMonth'].dt.to_timestamp()
        monthly = monthly.sort_values('date').reset_index(drop=True)
        
        if len(monthly) < 6:
            continue
        
        y = monthly['Qty'].values
        
        # Create features
        monthly['month'] = monthly['date'].dt.month
        monthly['months_since_start'] = np.arange(len(monthly))
        monthly['lag_1'] = monthly['Qty'].shift(1).fillna(method='bfill')
        monthly['rolling_mean_3'] = monthly['Qty'].rolling(3, min_periods=1).mean()
        
        # Seasonal index
        monthly_avg = monthly.groupby('month')['Qty'].transform('mean')
        overall_avg = monthly['Qty'].mean()
        monthly['seasonal_index'] = monthly_avg / overall_avg if overall_avg > 0 else 1
        
        feature_cols = ['month', 'months_since_start', 'lag_1', 'rolling_mean_3', 'seasonal_index']
        X = monthly[feature_cols].values
        
        if _HAS_XGBOOST and len(X) >= 6:
            model = XGBRegressor(
                n_estimators=50,
                learning_rate=0.1,
                max_depth=3,
                random_state=42,
                verbosity=0,
                n_jobs=-1
            )
            model.fit(X, y)
            
            # Generate future predictions
            last_date = monthly['date'].max()
            future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1), periods=forecast_periods, freq='MS')
            
            seasonal_indices = monthly.groupby('month')['seasonal_index'].first().to_dict()
            recent_values = list(monthly['Qty'].tail(3).values)
            
            future_predictions = []
            for i, future_date in enumerate(future_dates):
                future_month = future_date.month
                months_since_start = len(monthly) + i
                lag_1 = recent_values[-1]
                rolling_mean_3 = np.mean(recent_values[-3:])
                seasonal_idx = seasonal_indices.get(future_month, 1.0)
                
                future_features = [future_month, months_since_start, lag_1, rolling_mean_3, seasonal_idx]
                pred = max(model.predict([future_features])[0], 0)
                future_predictions.append(pred)
                recent_values.append(pred)
            
            results[product] = {
                'historical': monthly[['date', 'Qty']].rename(columns={'date': 'Invoice Date'}),
                'forecast': pd.DataFrame({'Date': future_dates, 'Forecast_Qty': future_predictions}),
                'total_forecast': float(np.sum(future_predictions)),
                'model_type': 'XGBoost'
            }
        else:
            # Fallback to seasonal linear regression
            from collections import defaultdict
            seasonal_factors = defaultdict(list)
            for idx, row in monthly.iterrows():
                seasonal_factors[row['month']].append(row['Qty'])
            
            monthly_averages = {m: np.mean(vals) for m, vals in seasonal_factors.items()}
            overall_mean = np.mean(list(monthly_averages.values())) if monthly_averages else y.mean()
            seasonal_indices = {m: avg / overall_mean if overall_mean > 0 else 1 for m, avg in monthly_averages.items()}
            
            # Trend
            x = np.arange(len(y)).astype(float)
            n = len(x)
            m_coef = (n * np.sum(x * y) - np.sum(x) * np.sum(y)) / (n * np.sum(x**2) - np.sum(x)**2)
            b_coef = (np.sum(y) - m_coef * np.sum(x)) / n
            
            last_date = monthly['date'].max()
            future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1), periods=forecast_periods, freq='MS')
            future_x = np.arange(len(monthly), len(monthly) + forecast_periods).astype(float)
            future_trend = m_coef * future_x + b_coef
            future_seasonal = np.array([seasonal_indices.get(d.month, 1) for d in future_dates])
            future_predictions = np.maximum(future_trend * future_seasonal, 0)
            
            results[product] = {
                'historical': monthly[['date', 'Qty']].rename(columns={'date': 'Invoice Date'}),
                'forecast': pd.DataFrame({'Date': future_dates, 'Forecast_Qty': future_predictions}),
                'total_forecast': float(np.sum(future_predictions)),
                'model_type': 'Seasonal Linear'
            }
    
    return results if results else None

def main():
    # Data file paths
    data_file = 'TDP Invoice Items Report - Troy Version.xlsx'
    product_file = 'TDP Product Code List.xlsx'
    
    # Get file modification time - this ensures cache refreshes when file changes
    file_mtime = get_file_mtime(data_file)
    
    # Load data - passes file_mtime so cache auto-invalidates when file changes
    df_original, meta = load_data_fast(data_file, product_file, _file_mtime=file_mtime)
    
    # Title with last updated
    st.markdown('<h1 class="main-header">TDP Data Insight</h1>', unsafe_allow_html=True)
    if meta.get('last_modified'):
        st.caption(f"Last updated: {meta['last_modified'].strftime('%d %b %Y %H:%M')}")
    
    if df_original is None:
        st.error(f"Data file not found: {data_file}")
        return
    
    # Refresh button in sidebar
    st.sidebar.header("Data")
    col1, col2 = st.sidebar.columns([2, 1])
    with col1:
        if 'min_date' in meta and 'max_date' in meta:
            st.caption(f"{meta['min_date'].strftime('%d %b %Y')} → {meta['max_date'].strftime('%d %b %Y')}")
    with col2:
        if st.button("🔄", help="Refresh data"):
            with st.spinner("Refreshing data..."):
                success, message = refresh_data_from_source(data_file)
            if success:
                st.cache_data.clear()
                st.toast(message, icon="✅")
                st.rerun()
            else:
                st.sidebar.error(message)
    
    st.sidebar.markdown("---")

    # Sidebar filters
    st.sidebar.header("Filters")
    
    all_types = meta.get('unique_types', [])
    all_statuses = meta.get('unique_statuses', [])
    all_categories = meta.get('unique_categories', [])
    all_item_types = meta.get('unique_item_types', [])
    all_furniture_groups = meta.get('unique_furniture_groups', [])
    
    # Date range filter
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
    
    # Fast multiselect filters with Select All checkboxes
    
    # Product Category
    if all_categories:
        cat_all = st.sidebar.checkbox("Select All", value=True, key="cat_select_all")
        if cat_all:
            selected_categories = st.sidebar.multiselect("Product Category", options=all_categories, default=all_categories, key='filter_categories')
        else:
            selected_categories = st.sidebar.multiselect("Product Category", options=all_categories, default=[], key='filter_categories_empty')
    else:
        selected_categories = []
    
    # Customer Type
    type_all = st.sidebar.checkbox("Select All", value=True, key="type_select_all")
    if type_all:
        selected_types = st.sidebar.multiselect("Customer Type", options=all_types, default=all_types, key='filter_types')
    else:
        selected_types = st.sidebar.multiselect("Customer Type", options=all_types, default=[], key='filter_types_empty')
    
    # Order Status
    status_all = st.sidebar.checkbox("Select All", value=True, key="status_select_all")
    if status_all:
        selected_statuses = st.sidebar.multiselect("Order Status", options=all_statuses, default=all_statuses, key='filter_statuses')
    else:
        selected_statuses = st.sidebar.multiselect("Order Status", options=all_statuses, default=[], key='filter_statuses_empty')
    
    with st.sidebar.expander("More Filters", expanded=False):
        selected_item_types = st.multiselect("Item Type", options=all_item_types, default=all_item_types, key='filter_item_types')
        selected_furniture_groups = st.multiselect("Furniture Group", options=all_furniture_groups, default=all_furniture_groups, key='filter_furniture') if all_furniture_groups else []
    
    # Tab selector
    st.sidebar.markdown("---")
    tab_options = ["📊 Overview", "💰 Revenue", "👥 Customers", "📦 Products", "🎨 Colours", "🌍 Geographic", "🔮 Forecast"]
    active_tab = st.sidebar.radio("Select Analysis", tab_options, key='active_tab')
    
    # Apply filters - cached in session state
    filter_key = (
        date_start, date_end,
        tuple(sorted(selected_types)) if selected_types else None,
        tuple(sorted(selected_statuses)) if selected_statuses else None,
        tuple(sorted(selected_categories)) if selected_categories else None,
        tuple(sorted(selected_item_types)) if selected_item_types else None,
        tuple(sorted(selected_furniture_groups)) if selected_furniture_groups else None
    )
    
    if 'filter_key' not in st.session_state or st.session_state.filter_key != filter_key:
        st.session_state.filter_key = filter_key
        st.session_state.df = apply_filters(
            df_original, date_start, date_end,
            tuple(selected_types) if selected_types else None,
            tuple(selected_statuses) if selected_statuses else None,
            tuple(selected_categories) if selected_categories else None,
            tuple(selected_item_types) if selected_item_types else None,
            tuple(selected_furniture_groups) if selected_furniture_groups else None
        )
        st.session_state.filter_hash = hash(filter_key)
    
    df = st.session_state.df
    filter_hash = st.session_state.filter_hash
    
    if len(df) == 0:
        st.warning("No data matches the selected filters.")
        return
    
    # Pre-extract arrays once for all tabs (fast)
    prices = df['Total Price'].values if 'Total Price' in df.columns else np.array([])
    dates = df['Invoice Date'].values if 'Invoice Date' in df.columns else np.array([])
    invoice_nos = df['Invoice No'].values if 'Invoice No' in df.columns else np.array([])
    customers = df['Company/Individual'].values if 'Company/Individual' in df.columns else np.array([])
    qty = df['Qty'].values if 'Qty' in df.columns else np.array([])
    
    # TAB 1: OVERVIEW
    if active_tab == "📊 Overview":
        metrics = calculate_business_metrics(filter_hash, prices, invoice_nos, customers, qty)
        pop_analysis = period_over_period_analysis_cached(filter_hash, dates, prices)
        
        # KPIs
        st.markdown("### Key Performance Indicators")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Total Revenue", f"£{metrics['total_revenue']:,.0f}")
        c2.metric("Total Orders", f"{metrics['total_orders']:,}")
        c3.metric("Avg Order Value", f"£{metrics['aov']:,.0f}")
        c4.metric("Unique Customers", f"{metrics['total_customers']:,}")
        c5.metric("Units Sold", f"{metrics['total_units']:,.0f}")
        c6.metric("Rev/Customer", f"£{metrics['revenue_per_customer']:,.0f}")
        
        # Growth metrics
        if pop_analysis:
            st.markdown("### Growth Trends")
            c1, c2, c3 = st.columns(3)
            c1.metric("30-Day Growth", f"{pop_analysis['30_day_growth']:+.1f}%")
            c2.metric("90-Day Growth", f"{pop_analysis['90_day_growth']:+.1f}%")
            c3.metric("Year-over-Year", f"{pop_analysis['yoy_growth']:+.1f}%")
    
    # TAB 2: REVENUE
    elif active_tab == "💰 Revenue":
        st.header("Revenue Analysis")
        
        c1, c2 = st.columns(2)
        
        with c1:
            monthly = get_monthly_revenue(filter_hash, dates, prices)
            if monthly is not None:
                fig = px.line(monthly, x='Month', y='Total Price', title='Monthly Revenue',
                             labels={'Total Price': 'Revenue (£)'})
                fig.update_traces(mode='lines+markers')
                fig.update_layout(height=350, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
        
        with c2:
            type_rev = get_type_revenue(filter_hash, df['Type'].values if 'Type' in df.columns else np.array([]), prices)
            if type_rev is not None:
                fig = px.bar(type_rev, x='Type', y='Total Price', title='Revenue by Type',
                            labels={'Total Price': 'Revenue (£)'})
                fig.update_layout(height=350, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
        
        st.markdown("---")
        c1, c2 = st.columns(2)
        
        with c1:
            quarterly = get_quarterly_revenue(filter_hash, dates, prices)
            if quarterly is not None:
                fig = px.bar(quarterly, x='Quarter', y='Total Price', title='Quarterly Revenue',
                            color='Total Price', color_continuous_scale='Viridis')
                fig.update_layout(height=350, showlegend=False, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
        
        with c2:
            if 'STATUS' in df.columns:
                status_rev = df.groupby('STATUS', dropna=True, as_index=False)['Total Price'].sum()
                fig = px.pie(status_rev, values='Total Price', names='STATUS', title='Revenue by Status', hole=0.4)
                fig.update_layout(height=350, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
    
    # TAB 3: CUSTOMERS
    elif active_tab == "👥 Customers":
        st.header("Customer Intelligence")
        
        customer_data = customer_value_analysis_fast(filter_hash, customers, dates, invoice_nos, prices)
        
        if customer_data is not None:
            c1, c2 = st.columns(2)
            
            with c1:
                top15 = customer_data.nlargest(15, 'Total Revenue')
                fig = px.bar(top15, x='Total Revenue', y='Customer', orientation='h',
                            title='Top 15 Customers', color='Total Revenue', color_continuous_scale='Blues')
                fig.update_layout(height=400, showlegend=False, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
            
            with c2:
                fig = px.histogram(customer_data, x='Days Since Last Purchase', title='Purchase Recency', nbins=25)
                fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
            
            st.subheader("Top 50 Customers by Revenue")
            st.dataframe(customer_data.nlargest(50, 'Total Revenue'), use_container_width=True, hide_index=True)
        else:
            st.info("Customer data not available.")
    
    # TAB 4: PRODUCTS
    elif active_tab == "📦 Products":
        st.header("Product Performance")
        
        c1, c2 = st.columns(2)
        
        with c1:
            if 'Short Description' in df.columns:
                prod_rev = df.groupby('Short Description', as_index=False)['Total Price'].sum()
                prod_rev = prod_rev.nlargest(10, 'Total Price')
                fig = px.bar(prod_rev, x='Total Price', y='Short Description', orientation='h',
                            title='Top 10 Products by Revenue')
                fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
        
        with c2:
            if 'Item Type' in df.columns:
                item_counts = df['Item Type'].value_counts(dropna=True).reset_index()
                item_counts.columns = ['Item Type', 'Count']
                fig = px.pie(item_counts, values='Count', names='Item Type', title='Item Type Distribution')
                fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
        
        # Top products table
        st.markdown("---")
        st.subheader("Top 20 Products by Revenue")
        if 'Short Description' in df.columns:
            prod_table = df.groupby('Short Description', as_index=False).agg({
                'Total Price': 'sum',
                'Qty': 'sum'
            }).nlargest(20, 'Total Price')
            prod_table.columns = ['Product', 'Revenue', 'Units Sold']
            prod_table['Revenue'] = prod_table['Revenue'].apply(lambda x: f"£{x:,.0f}")
            st.dataframe(prod_table, use_container_width=True, hide_index=True)
    
    # TAB 5: COLOURS
    elif active_tab == "🎨 Colours":
        st.header("Colour Performance Analysis")
        
        if 'Colour' not in df.columns or df['Colour'].dropna().empty:
            st.warning("No colour data available in the dataset.")
        else:
            # Filter to only products that have colour data
            df_with_colour = df[df['Colour'].notna() & (df['Colour'] != '')]
            
            if len(df_with_colour) == 0:
                st.warning("No products with colour information found.")
            else:
                # Overall colour popularity
                c1, c2 = st.columns(2)
                
                with c1:
                    # Revenue by colour
                    colour_rev = df_with_colour.groupby('Colour', as_index=False)['Total Price'].sum()
                    colour_rev = colour_rev.sort_values('Total Price', ascending=False)
                    fig = px.bar(colour_rev, x='Colour', y='Total Price', 
                                title='Revenue by Colour',
                                labels={'Total Price': 'Revenue (£)'},
                                color='Total Price', color_continuous_scale='Viridis')
                    fig.update_layout(height=400, showlegend=False, margin=dict(l=20, r=20, t=40, b=20))
                    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
                
                with c2:
                    # Quantity by colour
                    colour_qty = df_with_colour.groupby('Colour', as_index=False)['Qty'].sum()
                    colour_qty = colour_qty.sort_values('Qty', ascending=False)
                    fig = px.pie(colour_qty, values='Qty', names='Colour', 
                                title='Units Sold by Colour', hole=0.4)
                    fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
                    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
                
                st.markdown("---")
                
                # Product-specific colour analysis
                st.subheader("Colour Breakdown by Product")
                
                # Get products that have multiple colours
                product_colour_counts = df_with_colour.groupby('Short Description')['Colour'].nunique()
                multi_colour_products = product_colour_counts[product_colour_counts > 1].index.tolist()
                
                if multi_colour_products:
                    selected_product = st.selectbox(
                        "Select a product to see colour breakdown",
                        options=sorted(multi_colour_products),
                        key='colour_product_select'
                    )
                    
                    if selected_product:
                        product_df = df_with_colour[df_with_colour['Short Description'] == selected_product]
                        
                        c1, c2 = st.columns(2)
                        
                        with c1:
                            # Revenue by colour for selected product
                            prod_colour_rev = product_df.groupby('Colour', as_index=False)['Total Price'].sum()
                            prod_colour_rev = prod_colour_rev.sort_values('Total Price', ascending=False)
                            fig = px.bar(prod_colour_rev, x='Colour', y='Total Price',
                                        title=f'Revenue by Colour: {selected_product}',
                                        labels={'Total Price': 'Revenue (£)'},
                                        color='Colour')
                            fig.update_layout(height=350, showlegend=False, margin=dict(l=20, r=20, t=40, b=20))
                            st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
                        
                        with c2:
                            # Units by colour for selected product
                            prod_colour_qty = product_df.groupby('Colour', as_index=False)['Qty'].sum()
                            prod_colour_qty = prod_colour_qty.sort_values('Qty', ascending=False)
                            fig = px.pie(prod_colour_qty, values='Qty', names='Colour',
                                        title=f'Units Sold by Colour: {selected_product}', hole=0.4)
                            fig.update_layout(height=350, margin=dict(l=20, r=20, t=40, b=20))
                            st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
                        
                        # Table with colour breakdown
                        colour_table = product_df.groupby('Colour', as_index=False).agg({
                            'Total Price': 'sum',
                            'Qty': 'sum',
                            'Invoice No': 'nunique'
                        }).sort_values('Total Price', ascending=False)
                        colour_table.columns = ['Colour', 'Revenue', 'Units Sold', 'Orders']
                        colour_table['Avg Price/Unit'] = (colour_table['Revenue'] / colour_table['Units Sold']).round(2)
                        colour_table['Revenue'] = colour_table['Revenue'].apply(lambda x: f"£{x:,.0f}")
                        colour_table['Avg Price/Unit'] = colour_table['Avg Price/Unit'].apply(lambda x: f"£{x:,.2f}")
                        st.dataframe(colour_table, use_container_width=True, hide_index=True)
                else:
                    st.info("No products with multiple colour options found in the filtered data.")
                
                st.markdown("---")
                
                # Summary table - all colours
                st.subheader("Colour Summary")
                colour_summary = df_with_colour.groupby('Colour', as_index=False).agg({
                    'Total Price': 'sum',
                    'Qty': 'sum',
                    'Invoice No': 'nunique',
                    'Short Description': 'nunique'
                }).sort_values('Total Price', ascending=False)
                colour_summary.columns = ['Colour', 'Revenue', 'Units Sold', 'Orders', 'Products']
                colour_summary['Revenue'] = colour_summary['Revenue'].apply(lambda x: f"£{x:,.0f}")
                st.dataframe(colour_summary, use_container_width=True, hide_index=True)
    
    # TAB 6: GEOGRAPHIC
    elif active_tab == "🌍 Geographic":
        st.header("Geographic & Payment Insights")
        
        c1, c2 = st.columns(2)
        
        with c1:
            if 'Delivery Town' in df.columns:
                town_rev = df.groupby('Delivery Town', as_index=False)['Total Price'].sum()
                town_rev = town_rev.nlargest(15, 'Total Price')
                fig = px.bar(town_rev, x='Total Price', y='Delivery Town', orientation='h',
                            title='Top 15 Towns by Revenue', color='Total Price', color_continuous_scale='Viridis')
                fig.update_layout(height=450, showlegend=False, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
        
        with c2:
            if 'Payment Method' in df.columns:
                payment_rev = df.groupby('Payment Method', as_index=False)['Total Price'].sum()
                fig = px.pie(payment_rev, values='Total Price', names='Payment Method',
                            title='Revenue by Payment Method', hole=0.4)
                fig.update_layout(height=450, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
    
    # TAB 6: ADVANCED FORECASTING
    elif active_tab == "🔮 Forecast":
        st.header("Revenue Forecasting")
        
        model_info = "XGBoost with seasonality" if _HAS_XGBOOST else "Seasonal Linear Regression"
        st.markdown(f'<div class="insight-box"><b>Model:</b> {model_info} - captures trends, seasonality, and patterns for accurate predictions.</div>', unsafe_allow_html=True)
        
        c1, c2 = st.columns([1, 3])
        with c1:
            forecast_months = st.slider("Forecast Months", 3, 12, 6)
        
        with st.spinner("Generating forecast..."):
            results = predict_revenue_advanced(dates, prices, forecast_periods=forecast_months)
        
        if results:
            # Show forecast with confidence intervals
            fig = go.Figure()
            
            # Historical data
            fig.add_trace(go.Scatter(
                x=results['monthly_data']['Invoice Date'], 
                y=results['monthly_data']['Total Price'],
                mode='lines+markers', 
                name='Historical', 
                line=dict(color='#667eea', width=2)
            ))
            
            # Confidence interval (shaded area)
            if 'Lower_CI' in results['forecast'].columns:
                fig.add_trace(go.Scatter(
                    x=pd.concat([results['forecast']['Date'], results['forecast']['Date'][::-1]]),
                    y=pd.concat([results['forecast']['Upper_CI'], results['forecast']['Lower_CI'][::-1]]),
                    fill='toself',
                    fillcolor='rgba(40, 167, 69, 0.2)',
                    line=dict(color='rgba(255,255,255,0)'),
                    name='95% Confidence Interval',
                    showlegend=True
                ))
            
            # Forecast line
            fig.add_trace(go.Scatter(
                x=results['forecast']['Date'], 
                y=results['forecast']['Forecast'],
                mode='lines+markers', 
                name='Forecast', 
                line=dict(color='#28a745', width=3, dash='dash')
            ))
            
            fig.update_layout(
                title=f"Revenue Forecast ({results.get('model_type', 'Model')})",
                height=450, 
                hovermode='x unified',
                margin=dict(l=20, r=20, t=40, b=20),
                yaxis_title='Revenue (£)',
                xaxis_title='Date'
            )
            st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
            
            # Model Performance Metrics
            st.subheader("Model Performance")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("R² (Train)", f"{results.get('r2_train', 0):.3f}")
            c2.metric("R² (Test)", f"{results.get('r2_test', 0):.3f}")
            c3.metric("MAE", f"£{results.get('mae', 0):,.0f}")
            c4.metric("RMSE", f"£{results.get('rmse', 0):,.0f}")
            c5.metric("Trend", results.get('trend_direction', 'N/A').upper())
            
            # Feature importance (if XGBoost)
            if 'feature_importance' in results and results['feature_importance']:
                with st.expander("Top Predictive Features", expanded=False):
                    importance_df = pd.DataFrame([
                        {'Feature': k.replace('_', ' ').title(), 'Importance': f"{v:.1%}"}
                        for k, v in results['feature_importance'].items()
                    ])
                    st.dataframe(importance_df, use_container_width=True, hide_index=True)
            
            # Forecast table with confidence intervals
            st.subheader("Forecast Values")
            forecast_display = results['forecast'].copy()
            forecast_display['Date'] = forecast_display['Date'].dt.strftime('%B %Y')
            forecast_display['Forecast'] = forecast_display['Forecast'].apply(lambda x: f"£{x:,.0f}")
            if 'Lower_CI' in forecast_display.columns:
                forecast_display['Range'] = forecast_display.apply(
                    lambda row: f"£{row['Lower_CI']:,.0f} - £{row['Upper_CI']:,.0f}", axis=1
                )
                forecast_display = forecast_display[['Date', 'Forecast', 'Range']]
                forecast_display.columns = ['Month', 'Predicted Revenue', '95% Confidence Range']
            else:
                forecast_display = forecast_display[['Date', 'Forecast']]
                forecast_display.columns = ['Month', 'Predicted Revenue']
            st.dataframe(forecast_display, use_container_width=True, hide_index=True)
            
            # Summary stats
            total_forecast = results['forecast']['Forecast'].sum()
            avg_monthly = results['forecast']['Forecast'].mean()
            st.markdown(f"**Total Forecasted Revenue ({forecast_months} months):** £{total_forecast:,.0f} | **Average Monthly:** £{avg_monthly:,.0f}")
        else:
            st.warning("Insufficient data for forecasting. Need at least 12 months of historical data.")
        
        # Product Demand Forecast
        st.markdown("---")
        st.header("Product Demand Forecast")
        
        c1, c2 = st.columns([1, 3])
        with c1:
            prod_forecast_months = st.slider("Product Forecast Months", 3, 12, 6, key='prod_fc')
            top_n = st.slider("Top N Products", 3, 10, 5)
        
        products = df['Short Description'].values if 'Short Description' in df.columns else np.array([])
        
        with st.spinner("Generating product forecasts..."):
            prod_results = predict_product_demand_advanced(products, dates, qty, forecast_periods=prod_forecast_months, top_n=top_n)
        
        if prod_results:
            # Summary table
            summary = []
            for product, data in prod_results.items():
                hist_avg = data['historical']['Qty'].mean()
                forecast_avg = data['total_forecast'] / prod_forecast_months
                growth = ((forecast_avg / hist_avg) - 1) * 100 if hist_avg > 0 else 0
                summary.append({
                    'Product': product,
                    'Model': data.get('model_type', 'Linear'),
                    'Avg Monthly (Historical)': f"{hist_avg:.0f}",
                    'Avg Monthly (Forecast)': f"{forecast_avg:.0f}",
                    'Expected Change': f"{growth:+.1f}%",
                    f'Total ({prod_forecast_months}mo)': f"{data['total_forecast']:.0f}"
                })
            st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)
            
            # Select product
            selected = st.selectbox("View Product Forecast", list(prod_results.keys()))
            if selected:
                data = prod_results[selected]
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=data['historical']['Invoice Date'], 
                    y=data['historical']['Qty'],
                    mode='lines+markers', 
                    name='Historical', 
                    line=dict(color='#667eea', width=2)
                ))
                fig.add_trace(go.Scatter(
                    x=data['forecast']['Date'], 
                    y=data['forecast']['Forecast_Qty'],
                    mode='lines+markers', 
                    name='Forecast', 
                    line=dict(color='#28a745', width=2, dash='dash')
                ))
                fig.update_layout(
                    title=f"Demand Forecast: {selected} ({data.get('model_type', 'Model')})", 
                    height=400, 
                    margin=dict(l=20, r=20, t=40, b=20),
                    yaxis_title='Quantity',
                    xaxis_title='Date'
                )
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
        else:
            st.warning("Insufficient data for product forecasting.")

if __name__ == "__main__":
    main()
