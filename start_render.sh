#!/usr/bin/env bash
# Render start command: saves NSE top-20 history in the background and serves the dashboard.
export PYTHONPATH="$PWD:$PYTHONPATH"
python Option_chain/derivatives_history.py &
exec streamlit run Streaming/nifty50_streamlit_app.py \
  --server.port "${PORT:-8501}" --server.address 0.0.0.0 --server.headless true
