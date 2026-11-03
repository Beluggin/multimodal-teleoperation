# Runs MITT's tests, parser eval and phone page with no robot or API key.
# Motors, servos and the camera need the Pi: see the Quickstart in README.md.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Not root. The phone page saves its servo settings next to server.py.
RUN useradd --create-home mitt && chown -R mitt /app
USER mitt

EXPOSE 8123
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python3 -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8123/', timeout=2)"

# 0.0.0.0 is inside the container only. `docker run -p 127.0.0.1:8123:8123`
# decides who can reach it. Motors and servos stay off without their flags.
CMD ["python3", "src/tank_phone/server.py", "--bind", "0.0.0.0", "--port", "8123"]
