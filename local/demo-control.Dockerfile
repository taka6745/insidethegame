# Azure image for the demo operator (local/demo_control.py serve): the user backend's runtime, which has
# its dependencies, plus the script. Compose mounts the script into the same image instead.
ARG BASE
FROM ${BASE}
COPY demo_control.py /checks/demo_control.py
CMD ["python", "/checks/demo_control.py", "serve"]
