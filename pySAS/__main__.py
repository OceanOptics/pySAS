from pySAS.ui import app

# Start User Interface
# app.run_server(debug=True, use_reloader=False)
app.run(host='0.0.0.0')
# KNOWN BUG:If enable use_reloader multiple instances of Runner and opens multiple connection to the same serial ports
#           as the instance is never completely destroyed. It's only the case when debug=True
# Need host='0.0.0.0' to open to external network