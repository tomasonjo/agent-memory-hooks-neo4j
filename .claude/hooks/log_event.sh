#!/bin/bash
# Wrapper that invokes the Python event logger.
# Reads stdin (hook JSON) and pipes it to the Python script.
exec python3 "$(dirname "$0")/log_event.py"
