import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Page configuration
st.set_page_config(
    page_title="TDP Invoice Items Analysis",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .metric-container {
        background-color: #f0f2f6;
        border: 1px solid #e0e0e0;
        padding: 15px;
        border-radius: 10px;
        margin: 10px 0;
    }
    .main-header {
        color: #1f77b4;
        text-align: center;
        padding: 20px 0;
        border-bottom: 2px solid #1f77b4;
        margin-bottom: 30px;
    }
</style>
""", unsafe_allow_html=True)

@st.cache_data
def load_data():
    """Load and preprocess the Excel data"""
    try:
        df = pd.read_excel('TDP Invoice Items Report - Troy Version.xlsx', sheet_name='Data')
        
        # Clean and preprocess data
        df['Invoice Date'] = pd.to_datetime(df['Invoice Date'], errors='coerce')
        df['Order Date'] = pd.to_datetime(df['Order Date'], errors='coerce')
        df['Dispatch Date'] = pd.to_datetime(df['Dispatch Date'], errors='coerce')
        df['Completed Date'] = pd.to_datetime(df['Completed Date'], errors='coerce')
        
        # Fill missing values
        df['Total Price'] = df['Total Price'].fillna(0)
        df['Qty'] = df['Qty'].fillna(0)
        df['Weight (KG)'] = df['Weight (KG)'].fillna(0)
        
        # Create additional calculated fields
        df['Year'] = df['Invoice Date'].dt.year
        df['Month'] = df['Invoice Date'].dt.month
        df['Quarter'] = df['Invoice Date'].dt.quarter
        df['Year-Month'] = df['Invoice Date'].dt.to_period('M')
        
        return df
    except Exception as e:
        st.error(f"Error loading data: {str(e)}")
        return None

def main():
    st.markdown('<h1 class="main-header">🏢 TDP Invoice Items Analysis Dashboard</h1>', unsafe_allow_html=True)
    
    # Load data
    df = load_data()
    if df is None:
        return
    
    # Sidebar filters
    st.sidebar.header("🔍 Filters")
    
    # Date range filter
    if not df['Invoice Date'].isna().all():
        min_date = df['Invoice Date'].min().date()
        max_date = df['Invoice Date'].max().date()
        date_range = st.sidebar.date_input(
            "Select Date Range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )
        
        if len(date_range) == 2:
            df = df[
                (df['Invoice Date'].dt.date >= date_range[0]) & 
                (df['Invoice Date'].dt.date <= date_range[1])
            ]
    
    # Customer type filter
    customer_types = ['All'] + list(df['Type'].dropna().unique())
    selected_type = st.sidebar.selectbox("Customer Type", customer_types)
    if selected_type != 'All':
        df = df[df['Type'] == selected_type]
    
    # Status filter
    statuses = ['All'] + list(df['STATUS'].dropna().unique())
    selected_status = st.sidebar.selectbox("Status", statuses)
    if selected_status != 'All':
        df = df[df['STATUS'] == selected_status]
    
    # Item type filter
    item_types = ['All'] + list(df['Item Type'].dropna().unique())
    selected_item_type = st.sidebar.selectbox("Item Type", item_types)
    if selected_item_type != 'All':
        df = df[df['Item Type'] == selected_item_type]
    
    # Main content area
    if len(df) == 0:
        st.warning("No data matches the selected filters.")
        return
    
    # Key metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Total Records",
            f"{len(df):,}",
            delta=None
        )
    
    with col2:
        total_revenue = df['Total Price'].sum()
        st.metric(
            "Total Revenue",
            f"£{total_revenue:,.2f}",
            delta=None
        )
    
    with col3:
        total_qty = df['Qty'].sum()
        st.metric(
            "Total Quantity",
            f"{total_qty:,.0f}",
            delta=None
        )
    
    with col4:
        total_weight = df['Weight (KG)'].sum()
        st.metric(
            "Total Weight",
            f"{total_weight:,.1f} KG",
            delta=None
        )
    
    # Charts section
    st.markdown("---")
    
    # Revenue analysis
    st.header("📈 Revenue Analysis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Monthly revenue trend
        monthly_revenue = df.groupby(df['Invoice Date'].dt.to_period('M'))['Total Price'].sum().reset_index()
        monthly_revenue['Invoice Date'] = monthly_revenue['Invoice Date'].astype(str)
        
        fig_monthly = px.line(
            monthly_revenue,
            x='Invoice Date',
            y='Total Price',
            title='Monthly Revenue Trend',
            labels={'Total Price': 'Revenue (£)', 'Invoice Date': 'Month'}
        )
        fig_monthly.update_layout(height=400)
        st.plotly_chart(fig_monthly, use_container_width=True)
    
    with col2:
        # Revenue by customer type
        type_revenue = df.groupby('Type')['Total Price'].sum().reset_index()
        type_revenue = type_revenue.sort_values('Total Price', ascending=False)
        
        fig_type = px.bar(
            type_revenue,
            x='Type',
            y='Total Price',
            title='Revenue by Customer Type',
            labels={'Total Price': 'Revenue (£)', 'Type': 'Customer Type'}
        )
        fig_type.update_layout(height=400)
        st.plotly_chart(fig_type, use_container_width=True)
    
    # Product analysis
    st.header("📦 Product Analysis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Top products by revenue
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
    
    with col2:
        # Item type distribution
        item_type_counts = df['Item Type'].value_counts().reset_index()
        item_type_counts.columns = ['Item Type', 'Count']
        
        fig_items = px.pie(
            item_type_counts,
            values='Count',
            names='Item Type',
            title='Distribution by Item Type'
        )
        fig_items.update_layout(height=500)
        st.plotly_chart(fig_items, use_container_width=True)
    
    # Geographic analysis
    st.header("🗺️ Geographic Analysis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Top delivery towns
        delivery_towns = df.groupby('Delivery Town').agg({
            'Total Price': 'sum',
            'Qty': 'sum'
        }).reset_index().sort_values('Total Price', ascending=False).head(10)
        
        fig_towns = px.bar(
            delivery_towns,
            x='Total Price',
            y='Delivery Town',
            orientation='h',
            title='Top 10 Delivery Towns by Revenue',
            labels={'Total Price': 'Revenue (£)', 'Delivery Town': 'Town'}
        )
        fig_towns.update_layout(height=400)
        st.plotly_chart(fig_towns, use_container_width=True)
    
    with col2:
        # Payment method analysis
        payment_revenue = df.groupby('Payment Method')['Total Price'].sum().reset_index()
        
        fig_payment = px.pie(
            payment_revenue,
            values='Total Price',
            names='Payment Method',
            title='Revenue by Payment Method'
        )
        fig_payment.update_layout(height=400)
        st.plotly_chart(fig_payment, use_container_width=True)
    
    # Operational metrics
    st.header("⚙️ Operational Metrics")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Production status
        production_status = df['Production Status'].value_counts().reset_index()
        production_status.columns = ['Production Status', 'Count']
        
        fig_production = px.bar(
            production_status,
            x='Production Status',
            y='Count',
            title='Production Status Distribution',
            labels={'Count': 'Number of Items', 'Production Status': 'Status'}
        )
        fig_production.update_layout(height=400)
        st.plotly_chart(fig_production, use_container_width=True)
    
    with col2:
        # Weight analysis - FIXED VERSION
        weight_by_group = df.groupby('Furniture Group')['Weight (KG)'].sum().reset_index()
        weight_by_group = weight_by_group.sort_values('Weight (KG)', ascending=False).head(8)
        
        fig_weight = px.bar(
            weight_by_group,
            x='Furniture Group',
            y='Weight (KG)',
            title='Total Weight by Furniture Group',
            labels={'Weight (KG)': 'Weight (KG)', 'Furniture Group': 'Group'}
        )
        fig_weight.update_layout(
            height=400,
            xaxis={'tickangle': 45}  # CORRECT way to set tick angle
        )
        st.plotly_chart(fig_weight, use_container_width=True)
    
    # Data table
    st.header("📋 Detailed Data")
    
    # Summary statistics
    st.subheader("Summary Statistics")
    numeric_columns = ['Qty', 'Price', 'Total Price', 'Weight (KG)', 'Total Weight (KG)']
    summary_stats = df[numeric_columns].describe()
    st.dataframe(summary_stats, use_container_width=True)
    
    # Raw data with search and filter
    st.subheader("Raw Data")
    
    # Search functionality
    search_term = st.text_input("Search in data (searches across all text columns):")
    if search_term:
        text_columns = df.select_dtypes(include=['object']).columns
        mask = df[text_columns].astype(str).apply(
            lambda x: x.str.contains(search_term, case=False, na=False)
        ).any(axis=1)
        filtered_df = df[mask]
    else:
        filtered_df = df
    
    # Display options
    col1, col2 = st.columns(2)
    with col1:
        show_columns = st.multiselect(
            "Select columns to display:",
            options=df.columns.tolist(),
            default=['Company/Individual', 'Type', 'Invoice Date', 'Short Description', 
                    'Qty', 'Total Price', 'Delivery Town']
        )
    
    with col2:
        rows_to_show = st.slider("Number of rows to display:", 10, 1000, 100)
    
    if show_columns:
        st.dataframe(
            filtered_df[show_columns].head(rows_to_show),
            use_container_width=True
        )
    
    # Export functionality
    st.subheader("📤 Export Data")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("Download Filtered Data as CSV"):
            csv = filtered_df.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"tdp_invoice_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime='text/csv'
            )
    
    with col2:
        if st.button("Download Summary Statistics"):
            summary_csv = summary_stats.to_csv()
            st.download_button(
                label="Download Statistics CSV",
                data=summary_csv,
                file_name=f"tdp_summary_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime='text/csv'
            )

if __name__ == "__main__":
    main()