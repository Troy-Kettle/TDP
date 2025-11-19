# TDP Business Intelligence Suite - Enhancement Summary

## Overview
The Streamlit application has been massively improved with enterprise-grade business intelligence capabilities and machine learning forecasting. All improvements use UK English and maintain a professional, business-focused presentation.

## Key Enhancements

### 1. **Advanced Analytics Framework**
- **RFM Customer Segmentation**: Automatically segments customers into Champions, Loyal Customers, Potential Loyalists, At Risk, Need Attention, and Lost categories
- **ABC Analysis**: Identifies top 20% of products/customers generating 80% of revenue (Pareto principle)
- **Cohort Analysis**: Tracks customer retention over time with visual heatmaps
- **Period-over-Period Analysis**: 30-day, 90-day, and year-over-year growth metrics

### 2. **Machine Learning Forecasting** (NEW TAB)
- **Multiple ML Models**: 
  - Random Forest Regressor (with performance metrics: R² score, MAE)
  - Facebook Prophet (if installed)
  - ARIMA (if statsmodels installed)
  - Exponential Smoothing (if statsmodels installed)
- **Interactive Forecasting**: Adjustable forecast horizon (3-12 months)
- **Model Comparison**: Visual comparison of all models on single chart
- **Forecast Tables**: Detailed month-by-month revenue predictions

### 3. **Enhanced Visualisations**
- **Professional UI**: Modern gradient colour schemes and styled metrics
- **Interactive Charts**: All charts built with Plotly for full interactivity
- **Comprehensive Insights**: Insight boxes explain business implications
- **Tabbed Interface**: 7 organised tabs for different analysis areas:
  1. Revenue & Sales Analysis
  2. Customer Intelligence
  3. Product Performance
  4. Geographic Insights
  5. Operational Metrics
  6. Machine Learning Forecasts
  7. Raw Data & Export

### 4. **Business Intelligence Metrics**
- **Growth Trends**: 30-day, 90-day, and year-over-year comparisons with delta indicators
- **Customer Metrics**: Revenue per customer, customer lifetime value indicators
- **Product Performance**: Volume vs. value analysis, ABC categorisation
- **Revenue Breakdown**: By customer type, status, payment method, geography

### 5. **Improved Data Quality**
- **Enhanced Filters**: Added Furniture Group filter, sorted filter options
- **Data Validation**: Comprehensive data health indicators
- **Missing Data Handling**: Robust null-handling throughout
- **Better Defaults**: Smart column selection for data display

### 6. **Professional Styling**
- **Modern CSS**: Gradient backgrounds, styled metrics, professional colour palette
- **Responsive Layout**: Optimised for wide screens with proper column layouts
- **Visual Hierarchy**: Clear section headers, insight boxes, organised information flow
- **UK English**: All text, labels, and insights use British English

## Installation

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Optional Advanced ML Libraries
For full ML forecasting capabilities:
```bash
pip install prophet statsmodels pydeck
```

## Running the Application

```bash
streamlit run streamlit_app.py
```

The application will open in your browser at `http://localhost:8501`

## Data Requirements

The application expects an Excel file named `TDP Invoice Items Report - Troy Version.xlsx` with a sheet named `Data` containing the following columns:

**Required Columns**:
- Invoice No
- Invoice Date
- Total Price
- Company/Individual
- Type
- STATUS

**Optional Columns** (enhance functionality):
- Order Date, Dispatch Date, Completed Date
- Item Type
- Short Description
- Qty
- Price, Discount
- Weight (KG)
- Delivery Town
- Payment Method
- Production Status
- Furniture Group

## Key Features by Tab

### Tab 1: Revenue & Sales Analysis
- Monthly revenue trends with markers
- Quarterly performance comparison
- Revenue by customer type
- Revenue distribution by order status

### Tab 2: Customer Intelligence
- RFM segmentation with visual distribution
- Top 20 customers by value
- ABC analysis (Pareto principle)
- Cumulative revenue curves
- Customer retention cohort heatmaps

### Tab 3: Product Performance
- Top 10 products by revenue
- Item type distribution
- ABC analysis for products
- Volume vs. value scatter analysis

### Tab 4: Geographic Insights
- Top 15 towns by revenue
- Payment method distribution
- Revenue concentration visualisations

### Tab 5: Operational Metrics
- Weight by furniture group
- Production status distribution
- Operational KPIs

### Tab 6: Machine Learning Forecasts
- Historical revenue trends
- Multi-model forecast comparison
- Model performance metrics
- Detailed forecast tables
- Adjustable forecast horizon (3-12 months)

### Tab 7: Raw Data & Export
- Summary statistics
- Searchable data table
- Column selection
- CSV export functionality

## Technical Highlights

### Performance Optimisations
- `@st.cache_data` decorator for data loading
- Efficient data aggregation with pandas
- Minimal recomputation on filter changes

### Error Handling
- Graceful degradation when optional libraries missing
- Robust null/missing data handling
- Clear user messaging for data issues

### Scalability
- Handles large datasets efficiently
- Modular function architecture
- Reusable analysis components

## Future Enhancement Opportunities

1. **Real-time Data Integration**: Connect to live database instead of Excel file
2. **User Authentication**: Add role-based access control
3. **Custom Alerts**: Email/SMS alerts for KPI thresholds
4. **What-If Analysis**: Interactive scenario modelling
5. **Report Scheduling**: Automated PDF report generation
6. **Advanced Clustering**: K-means customer segmentation
7. **Anomaly Detection**: Automatic detection of unusual patterns

## Business Value

This enhanced application provides:
- **Strategic Insights**: Identify high-value customers and products
- **Predictive Intelligence**: ML-powered revenue forecasting
- **Data-Driven Decisions**: Comprehensive metrics and visualisations
- **Operational Efficiency**: Quick access to key business indicators
- **Professional Presentation**: Board-ready visualisations and metrics

## Support

For issues or questions:
1. Check data file format and column names
2. Ensure all required dependencies are installed
3. Review console output for error messages
4. Verify Excel file is in same directory as script

---

**Version**: 2.0  
**Last Updated**: October 2025  
**Author**: Advanced Business Intelligence Enhancement
