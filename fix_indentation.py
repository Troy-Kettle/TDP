"""Fix indentation for tab structure in streamlit_app.py"""

# Read the file
with open('streamlit_app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find key markers
in_tab3 = False
in_tab4 = False
in_tab5 = False
in_tab6 = False
tab_start_line = None

# Track which lines need extra indentation
for i, line in enumerate(lines):
    if '# TAB 3: CUSTOMER INTELLIGENCE' in line:
        in_tab3 = True
        tab_start_line = i
    elif '# Product Performance' in line and 'st.header' in lines[i+1]:
        in_tab3 = False
        in_tab4 = True
    elif '# Geographic Insights' in line and 'st.header' in lines[i+1]:
        in_tab4 = False
        in_tab5 = True
    elif '# Revenue Forecasting' in line or '# Forecasting' in line:
        in_tab5 = False
        in_tab6 = True
    elif 'if __name__ == "__main__":' in line:
        break
    
    # Add indentation for lines that need it
    if i > tab_start_line and tab_start_line is not None:
        if (in_tab3 or in_tab4 or in_tab5 or in_tab6) and not line.strip().startswith('#'):
            if not line.startswith('    # TAB'):
                # Add 4 spaces if not already indented enough
                if line.startswith('    ') and not line.startswith('        '):
                    lines[i] = '    ' + line

# Write back
with open('streamlit_app_fixed.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Fixed indentation written to streamlit_app_fixed.py")
