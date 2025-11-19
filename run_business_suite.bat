@echo off
echo ===============================================
echo         TDP Analytics Suite
echo      Clean, Professional Analytics
echo ===============================================
echo.
echo Starting the application...
echo Please wait while the dashboard loads...
echo.
streamlit run tdp_business_suite.py --server.port 8505
echo.
echo Dashboard stopped. Press any key to exit.
pause