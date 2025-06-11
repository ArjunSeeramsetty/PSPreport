FROM astrocrpublic.azurecr.io/runtime:3.0-2

# ---- ADD THESE FOUR LINES ----
USER root
RUN apt-get update && apt-get install -y default-jdk build-essential && apt-get clean && rm -rf /var/lib/apt/lists/*
# ------------------------------
# # Start from the official Airflow image to get all its dependencies
# FROM apache/airflow:3.0.1

# # Switch to root to install dependencies, then switch back to the airflow user
# USER root
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     libpq-dev \
#     && apt-get clean && rm -rf /var/lib/apt/lists/*

# # The only Python dependency our script needs is selenium
# # Airflow is already included in the base image
# USER airflow
# RUN pip install --no-cache-dir selenium==4.33.0

# # Copy your DAG file into the image
# COPY dags/pdf_pipeline_dag.py /opt/airflow/dags/pdf_pipeline_dag.py