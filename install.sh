#!/bin/bash

# Allow current user access log file
sudo usermod -aG root $USER

# Install python3
sudo apt install -y python3 python3-full python3-pip

# Create env
python3 -m venv .env

# Install python packages
./.env/bin/python3 -m pip install -U pip setuptools
./.env/bin/python3 -m pip install -r requirements.txt
