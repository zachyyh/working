FROM python:3.12-slim

# Install Docker CLI (to talk to host Docker via socket)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates sudo bash iproute2 && \
    curl -fsSL https://get.docker.com | sh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install ContainerLab
RUN bash -c "$(curl -sL https://get.containerlab.dev)"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN ansible-galaxy collection install vyos.vyos community.docker community.general community.postgresql ansible.posix

COPY . .

# Ensure workdirs exist
RUN mkdir -p /app/clab-workdir

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000","--reload"]
