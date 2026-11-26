#!/usr/bin/env bash
# Render start command: saves the NSE top-20 history, the NIFTY synthetic-future readings and the
# cumulative-OI snapshots in the background, and serves the dashboard.
export PYTHONPATH="$PWD:$PYTHONPATH"
python Option_chain/derivatives_history.py &
python Option_chain/synthetic_future.py &
python Option_chain/synthetic_future_cum_oi.py &
exec streamlit run Streaming/nifty50_streamlit_app.py \
  --server.port "${PORT:-8501}" --server.address 0.0.0.0 --server.headless true
